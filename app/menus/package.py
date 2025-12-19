import json
import sys
import os
from datetime import datetime

import requests
from rich.align import Align
from app.service.auth import AuthInstance
from app.client.engsel import (
    get_family,
    get_package,
    get_addons,
    get_package_details,
    send_api_request,
    unsubscribe,
)
from app.client.ciam import get_auth_code
from app.service.bookmark import BookmarkInstance
from app.client.purchase.redeem import settlement_bounty, settlement_loyalty, bounty_allotment
from app.menus.util import clear_screen, pause, display_html
from app.client.purchase.qris import show_qris_payment
from app.client.purchase.ewallet import show_multipayment
from app.client.purchase.balance import settlement_balance
from app.type_dict import PaymentItem
from app.menus.purchase import purchase_n_times, purchase_n_times_by_option_code
from app.menus.util import format_quota_byte
from app.service.decoy import DecoyInstance
from app.console import console, print_cyber_panel, cyber_input, loading_animation, print_step
from rich.table import Table
from rich.panel import Panel

# Indonesian month short names mapping
_MONTH_ID = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "Mei", 6: "Jun",
    7: "Jul", 8: "Agu", 9: "Sep", 10: "Okt", 11: "Nov", 12: "Des"
}


def _normalize_ts_input(ts):
    """
    Normalize various timestamp representations into seconds (int).
    - Accepts int/float (seconds or milliseconds), numeric strings (seconds or ms).
    - Returns None if value cannot be interpreted as timestamp.
    """
    try:
        if ts is None:
            return None

        # If already numeric types
        if isinstance(ts, (int, float)):
            val = int(ts)
        # Numeric string (allow negative? usually no — keep simple)
        elif isinstance(ts, str):
            s = ts.strip()
            # Accept purely numeric strings
            if s.isdigit():
                val = int(s)
            else:
                # Try to parse ISO-like numeric fraction? not necessary here
                return None
        else:
            return None

        # If value looks like milliseconds ( > year 3000 in seconds ), convert to seconds.
        # Use conservative threshold: anything > 3_000_000_000 -> probably ms.
        if val > 3_000_000_000:
            val = int(val / 1000)
        return val
    except Exception:
        return None


def _format_ts(ts):
    try:
        norm = _normalize_ts_input(ts)
        if norm is not None:
            dt = datetime.fromtimestamp(int(norm))
            mon = _MONTH_ID.get(dt.month, dt.strftime("%b"))
            return f"{dt.day:02d} {mon} {dt.year} {dt.strftime('%H:%M:%S')}"
        # If it's a non-numeric string (maybe ISO), try to return it as-is
        return str(ts)
    except Exception:
        return str(ts)


def _days_until(ts):
    try:
        norm = _normalize_ts_input(ts)
        if norm is None:
            return None
        now = datetime.now()
        target = datetime.fromtimestamp(int(norm))
        delta = target - now
        return delta.days
    except Exception:
        return None


def _get_bar_width(min_w: int = 12, max_w: int = 48, reserved: int = 60) -> int:
    try:
        total = console.size.width or 80
        avail = max(10, total - reserved)
        return max(min_w, min(max_w, avail))
    except Exception:
        return min_w


def _render_progress_bar(remaining: int, total: int, width: int | None = None, fill_char: str = "▒", empty_char: str = "░"):
    """
    Render a horizontal bar that reflects remaining / total.
    - remaining, total: numbers (use bytes for DATA)
    - width: number of character cells for the bar (auto-calculated if None)
    Color rules:
      pct >= 100 -> neon_green
      pct >= 50  -> neon_yellow
      pct >= 20  -> orange1
      pct < 20   -> red
    """
    try:
        if width is None:
            width = _get_bar_width()

        if not isinstance(total, (int, float)) or total <= 0:
            bar = empty_char * width
            return f"[dim]{bar}[/] N/A"

        rem_clamped = max(0, min(remaining, total))
        frac = rem_clamped / total
        filled = int(round(frac * width))
        filled_part = fill_char * filled
        empty_part = empty_char * (width - filled)
        pct = int(round(frac * 100))

        # color selection (cleaned)
        if pct >= 100:
            color = "neon_green"
        elif pct >= 50:
            color = "neon_yellow"
        elif pct >= 20:
            color = "orange1"
        else:
            color = "red"

        return f"[{color}]{filled_part}[/][dim]{empty_part}[/] {pct}%"
    except Exception:
        bar = empty_char * width
        return f"[dim]{bar}[/] 0%"


def _compute_quotas_summary(quotas):
    total = 0
    remaining = 0
    for q in quotas:
        for b in q.get("benefits", []):
            try:
                if b.get("data_type") == "DATA":
                    t = int(b.get("total") or 0)
                    r = int(b.get("remaining") if b.get("remaining") is not None else t)
                    total += t
                    remaining += r
            except Exception:
                continue
    return remaining, total


def show_package_details(api_key, tokens, package_option_code, is_enterprise, option_order = -1):
    active_user = AuthInstance.active_user
    subscription_type = active_user.get("subscription_type", "") if active_user else ""

    clear_screen()

    with loading_animation("Fetching package details..."):
        package = get_package(api_key, tokens, package_option_code)

    if not package:
        console.print("[error]Failed to load package details.[/]")
        pause()
        return False

    price = package["package_option"].get("price", "")
    detail = display_html(package["package_option"].get("tnc", ""))
    validity = package["package_option"].get("validity", "")

    option_name = package.get("package_option", {}).get("name","")
    family_name = package.get("package_family", {}).get("name","")
    variant_name = package.get("package_detail_variant", "").get("name","")

    title = f"{family_name} - {variant_name} - {option_name}".strip()

    parent_code = package.get("package_addon", {}).get("parent_code","")
    if parent_code == "":
        parent_code = "N/A"

    token_confirmation = package.get("token_confirmation", "")
    ts_to_sign = package.get("timestamp", "")
    payment_for = package.get("package_family", {}).get("payment_for", "")

    payment_items = [
        PaymentItem(
            item_code=package_option_code,
            product_type="",
            item_price=price,
            item_name=f"{variant_name} {option_name}".strip(),
            tax=0,
            token_confirmation=token_confirmation,
        )
    ]

    # Details Table
    details_table = Table(show_header=False, box=None, padding=(0, 1))
    details_table.add_column("Key", style="neon_cyan", justify="right")
    details_table.add_column("Value", style="bold white")

    details_table.add_row("Nama:", title)
    details_table.add_row("Harga:", f"Rp {price}")
    details_table.add_row("Payment For:", str(payment_for))
    details_table.add_row("Masa Aktif Paket:", str(validity))
    details_table.add_row("Point:", str(package.get('package_option', {}).get('point', "")))
    details_table.add_row("Plan Type:", package.get('package_family', {}).get('plan_type', ""))
    details_table.add_row("Kode Paket:", f"[neon_yellow]{package_option_code}[/]")
    details_table.add_row("Parent Code:", parent_code)

    # Try multiple possible locations for activation/reset timestamps (package-level, option-level, nested)
    activated_ts = (
        package.get("activated_at")
        or package.get("active_since")
        or package.get("package_option", {}).get("activated_at")
        or package.get("package_option", {}).get("active_since")
        or package.get("package", {}).get("activated_at")
        or package.get("package", {}).get("active_since")
    )
    reset_ts = (
        package.get("reset_at")
        or package.get("reset_quota_at")
        or package.get("package_option", {}).get("reset_at")
        or package.get("package_option", {}).get("reset_quota_at")
        or package.get("package", {}).get("reset_at")
        or package.get("package", {}).get("reset_quota_at")
    )

    if activated_ts:
        details_table.add_row("Masa Aktif Kuota:", _format_ts(activated_ts))
    if reset_ts:
        days_left = _days_until(reset_ts)
        if days_left is not None:
            details_table.add_row("Akhir Reset Kuota:", f"{_format_ts(reset_ts)} (sisa {days_left} hari)")
        else:
            details_table.add_row("Akhir Reset Kuota:", _format_ts(reset_ts))

    print_cyber_panel(details_table, title="DETAIL PAKET")

    benefits = package.get("package_option", {}).get("benefits", [])
    if benefits and isinstance(benefits, list):
        benefit_table = Table(show_header=True, header_style="neon_pink", box=None)
        benefit_table.add_column("Benefit Name", style="white")
        benefit_table.add_column("Type", style="dim", width=12)
        benefit_table.add_column("Kuota", style="neon_green")

        bar_width = _get_bar_width()

        for benefit in benefits:
            data_type = benefit.get('data_type', '')
            remaining = int(benefit.get('remaining', benefit.get('total', 0)) or 0)
            total = int(benefit.get('total', 0) or 0)

            # Build numeric display above the bar
            if data_type == "DATA" and total > 0:
                # format bytes
                if remaining >= 1_000_000_000:
                    rem_display = f"{remaining / (1024 ** 3):.2f} GB"
                elif remaining >= 1_000_000:
                    rem_display = f"{remaining / (1024 ** 2):.2f} MB"
                elif remaining >= 1_000:
                    rem_display = f"{remaining / 1024:.2f} KB"
                else:
                    rem_display = f"{remaining} B"

                if total >= 1_000_000_000:
                    tot_display = f"{total / (1024 ** 3):.2f} GB"
                elif total >= 1_000_000:
                    tot_display = f"{total / (1024 ** 2):.2f} MB"
                elif total >= 1_000:
                    tot_display = f"{total / 1024:.2f} KB"
                else:
                    tot_display = f"{total} B"

                numbers = f"{rem_display} / {tot_display}"
            elif data_type == "VOICE" and total > 0:
                numbers = f"{remaining/60:.2f} m / {total/60:.2f} m"
            elif data_type == "TEXT" and total > 0:
                numbers = f"{remaining} / {total} SMS"
            else:
                numbers = f"{remaining} / {total}"

            # Bar reflects remaining / total (full when remaining==total)
            if benefit.get("is_unlimited", False) or total == 0:
                bar = _render_progress_bar(0, 1, width=bar_width)
                numbers = "Unlimited" if benefit.get("is_unlimited", False) else numbers
            else:
                bar = _render_progress_bar(remaining, total, width=bar_width)

            kuota_cell = f"{numbers}\n{bar}"
            benefit_table.add_row(benefit.get('name', 'N/A'), data_type, kuota_cell)

        print_cyber_panel(benefit_table, title="BENEFITS")

    with loading_animation("Checking addons..."):
        addons = get_addons(api_key, tokens, package_option_code)

    console.print(Panel(detail or "No terms available.", title="[neon_pink]SnK MyXL[/]", border_style="dim white"))

    in_package_detail_menu = True
    while in_package_detail_menu:
        menu_table = Table(show_header=False, box=None)
        menu_table.add_row("1", "Beli dengan Pulsa")
        menu_table.add_row("2", "Beli dengan E-Wallet")
        menu_table.add_row("3", "Bayar dengan QRIS")
        menu_table.add_row("4", "Pulsa + Decoy")
        menu_table.add_row("5", "Pulsa + Decoy V2")
        menu_table.add_row("6", "QRIS + Decoy (+1K)")
        menu_table.add_row("7", "QRIS + Decoy V2")
        menu_table.add_row("8", "Pulsa N kali")

        if payment_for == "":
            payment_for = "BUY_PACKAGE"

        if payment_for == "REDEEM_VOUCHER":
            menu_table.add_row("B", "Ambil sebagai bonus")
            menu_table.add_row("BA", "Kirim bonus")
            menu_table.add_row("L", "Beli dengan Poin")

        if option_order != -1:
            menu_table.add_row("0", "Tambah ke Bookmark")
        menu_table.add_row("00", "Kembali ke daftar paket")

        print_cyber_panel(menu_table, title="ACTIONS")

        choice = cyber_input("Pilihan")
        if choice == "00":
            return False
        elif choice == "0" and option_order != -1:
            success = BookmarkInstance.add_bookmark(
                family_code=package.get("package_family", {}).get("package_family_code",""),
                family_name=package.get("package_family", {}).get("name",""),
                is_enterprise=is_enterprise,
                variant_name=variant_name,
                option_name=option_name,
                order=option_order,
            )
            if success:
                console.print("[neon_green]Paket berhasil ditambahkan ke bookmark.[/]")
            else:
                console.print("[warning]Paket sudah ada di bookmark.[/]")
            pause()
            continue

        elif choice == '1':
            settlement_balance(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True
            )
            pause()
            return True
        elif choice == '2':
            show_multipayment(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True,
            )
            pause()
            return True
        elif choice == '3':
            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                payment_for,
                True,
            )
            pause()
            return True
        elif choice == '4':
            decoy = DecoyInstance.get_decoy("balance")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            overwrite_amount = price + decoy_package_detail["package_option"]["price"]
            res = settlement_balance(
                api_key,
                tokens,
                payment_items,
                payment_for,
                False,
                overwrite_amount=overwrite_amount,
            )

            if res and res.get("status", "") != "SUCCESS":
                error_msg = res.get("message", "Unknown error")
                if "Bizz-err.Amount.Total" in error_msg:
                    error_msg_arr = error_msg.split("=")
                    valid_amount = int(error_msg_arr[1].strip())

                    print(f"Adjusted total amount to: {valid_amount}")
                    res = settlement_balance(
                        api_key,
                        tokens,
                        payment_items,
                        payment_for,
                        False,
                        overwrite_amount=valid_amount,
                    )
                    if res and res.get("status", "") == "SUCCESS":
                        console.print("[neon_green]Purchase successful![/]")
            else:
                console.print("[neon_green]Purchase successful![/]")
            pause()
            return True
        elif choice == '5':
            decoy = DecoyInstance.get_decoy("balance")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            overwrite_amount = price + decoy_package_detail["package_option"]["price"]
            res = settlement_balance(
                api_key,
                tokens,
                payment_items,
                "🤫",
                False,
                overwrite_amount=overwrite_amount,
                token_confirmation_idx=1
            )

            if res and res.get("status", "") != "SUCCESS":
                error_msg = res.get("message", "Unknown error")
                if "Bizz-err.Amount.Total" in error_msg:
                    error_msg_arr = error_msg.split("=")
                    valid_amount = int(error_msg_arr[1].strip())

                    print(f"Adjusted total amount to: {valid_amount}")
                    res = settlement_balance(
                        api_key,
                        tokens,
                        payment_items,
                        "🤫",
                        False,
                        overwrite_amount=valid_amount,
                        token_confirmation_idx=-1
                    )
                    if res and res.get("status", "") == "SUCCESS":
                        console.print("[neon_green]Purchase successful![/]")
            else:
                console.print("[neon_green]Purchase successful![/]")
            pause()
            return True
        elif choice == '6':
            decoy = DecoyInstance.get_decoy("qris")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            console.print(Panel(
                f"Harga Paket Utama: Rp {price}\nHarga Paket Decoy: Rp {decoy_package_detail['package_option']['price']}\n\nSilahkan sesuaikan amount (trial & error, 0 = malformed)",
                title="DECOY QRIS INFO",
                border_style="warning"
            ))

            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                "SHARE_PACKAGE",
                True,
                token_confirmation_idx=1
            )

            pause()
            return True
        elif choice == '7':
            decoy = DecoyInstance.get_decoy("qris0")

            decoy_package_detail = get_package(
                api_key,
                tokens,
                decoy["option_code"],
            )

            if not decoy_package_detail:
                console.print("[error]Failed to load decoy package details.[/]")
                pause()
                return False

            payment_items.append(
                PaymentItem(
                    item_code=decoy_package_detail["package_option"]["package_option_code"],
                    product_type="",
                    item_price=decoy_package_detail["package_option"]["price"],
                    item_name=decoy_package_detail["package_option"]["name"],
                    tax=0,
                    token_confirmation=decoy_package_detail["token_confirmation"],
                )
            )

            console.print(Panel(
                f"Harga Paket Utama: Rp {price}\nHarga Paket Decoy: Rp {decoy_package_detail['package_option']['price']}\n\nSilahkan sesuaikan amount (trial & error, 0 = malformed)",
                title="DECOY QRIS INFO",
                border_style="warning"
            ))

            show_qris_payment(
                api_key,
                tokens,
                payment_items,
                "SHARE_PACKAGE",
                True,
                token_confirmation_idx=1
            )

            pause()
            return True
        elif choice == '8':
            use_decoy_for_n_times = cyber_input("Use decoy package? (y/n)").strip().lower() == 'y'
            n_times_str = cyber_input("Enter number of times to purchase (e.g., 3)").strip()

            delay_seconds_str = cyber_input("Enter delay between purchases in seconds (e.g., 25)").strip()
            if not delay_seconds_str.isdigit():
                delay_seconds_str = "0"

            try:
                n_times = int(n_times_str)
                if n_times < 1:
                    raise ValueError("Number must be at least 1.")
            except ValueError:
                console.print("[error]Invalid number entered. Please enter a valid integer.[/]")
                pause()
                continue
            purchase_n_times_by_option_code(
                n_times,
                option_code=package_option_code,
                use_decoy=use_decoy_for_n_times,
                delay_seconds=int(delay_seconds_str),
                pause_on_success=False,
                token_confirmation_idx=1
            )
        elif choice.lower() == 'b':
            settlement_bounty(
                api_key=api_key,
                tokens=tokens,
                token_confirmation=token_confirmation,
                ts_to_sign=ts_to_sign,
                payment_target=package_option_code,
                price=price,
                item_name=variant_name
            )
            pause()
            return True
        elif choice.lower() == 'ba':
            destination_msisdn = cyber_input("Masukkan nomor tujuan bonus (mulai dengan 62)").strip()
            bounty_allotment(
                api_key=api_key,
                tokens=tokens,
                ts_to_sign=ts_to_sign,
                destination_msisdn=destination_msisdn,
                item_name=option_name,
                item_code=package_option_code,
                token_confirmation=token_confirmation,
            )
            pause()
            return True
        elif choice.lower() == 'l':
            settlement_loyalty(
                api_key=api_key,
                tokens=tokens,
                token_confirmation=token_confirmation,
                ts_to_sign=ts_to_sign,
                payment_target=package_option_code,
                price=price,
            )
            pause()
            return True
        else:
            console.print("[warning]Purchase cancelled.[/]")
            return False
    pause()
    sys.exit(0)


def get_packages_by_family(
    family_code: str,
    is_enterprise: bool | None = None,
    migration_type: str | None = None
):
    api_key = AuthInstance.api_key
    tokens = AuthInstance.get_active_tokens()
    if not tokens:
        console.print("[error]No active user tokens found.[/]")
        pause()
        return None

    packages = []

    with loading_animation("Fetching family packages..."):
        data = get_family(
            api_key,
            tokens,
            family_code,
            is_enterprise,
            migration_type
        )

    if not data:
        console.print("[error]Failed to load family data.[/]")
        pause()
        return None

    price_currency = "Rp"
    rc_bonus_type = data["package_family"].get("rc_bonus_type", "")
    if rc_bonus_type == "MYREWARDS":
        price_currency = "Poin"

    in_package_menu = True
    while in_package_menu:
        clear_screen()

        # Family Info Panel
        family_table = Table(show_header=False, box=None)
        family_table.add_column("Key", style="neon_cyan", justify="right")
        family_table.add_column("Value", style="bold white")

        family_table.add_row("Family Name:", data['package_family']['name'])
        family_table.add_row("Family Code:", family_code)
        family_table.add_row("Family Type:", data['package_family']['package_family_type'])
        family_table.add_row("Variant Count:", str(len(data['package_variants'])))

        print_cyber_panel(family_table, title="FAMILY INFO")

        # Packages List
        pkg_table = Table(show_header=True, header_style="neon_pink", box=None, padding=(0, 1))
        pkg_table.add_column("No", style="neon_green", justify="right", width=4)
        pkg_table.add_column("Package Name", style="bold white")
        pkg_table.add_column("Price", style="yellow")

        package_variants = data["package_variants"]

        option_number = 1

        # Rebuild packages list each render to ensure correct indexing if needed,
        # though strictly speaking it's static per fetch.
        packages = []

        for variant in package_variants:
            variant_name = variant["name"]
            # pkg_table.add_row("", f"[dim]{variant_name}[/]", "") # Section header style

            for option in variant["package_options"]:
                option_name = option["name"]
                price_display = f"{price_currency} {option['price']}"

                full_name = f"{variant_name} - {option_name}"

                packages.append({
                    "number": option_number,
                    "variant_name": variant_name,
                    "option_name": option_name,
                    "price": option["price"],
                    "code": option["package_option_code"],
                    "option_order": option["order"]
                })

                pkg_table.add_row(str(option_number), full_name, price_display)
                option_number += 1

        print_cyber_panel(pkg_table, title="AVAILABLE PACKAGES")

        console.print("[dim]00. Kembali ke menu utama[/]")
        pkg_choice = cyber_input("Pilih paket (nomor)")
        if pkg_choice == "00":
            in_package_menu = False
            return None

        if isinstance(pkg_choice, str) == False or not pkg_choice.isdigit():
            console.print("[error]Input tidak valid. Silakan masukan nomor paket.[/]")
            pause()
            continue

        selected_pkg = next((p for p in packages if p["number"] == int(pkg_choice)), None)

        if not selected_pkg:
            console.print("[error]Paket tidak ditemukan. Silakan masukan nomor yang benar.[/]")
            pause()
            continue

        show_package_details(
            api_key,
            tokens,
            selected_pkg["code"],
            is_enterprise,
            option_order=selected_pkg["option_order"],
        )

    return packages


def fetch_my_packages():
    in_my_packages_menu = True
    while in_my_packages_menu:
        api_key = AuthInstance.api_key
        tokens = AuthInstance.get_active_tokens()
        if not tokens:
            console.print("[error]No active user tokens found.[/]")
            pause()
            return None

        id_token = tokens.get("id_token")

        path = "api/v8/packages/quota-details"

        payload = {
            "is_enterprise": False,
            "lang": "en",
            "family_member_id": ""
        }

        with loading_animation("Fetching my packages..."):
            res = send_api_request(api_key, path, payload, id_token, "POST")

        if res.get("status") != "SUCCESS":
            console.print("[error]Failed to fetch packages[/]")
            console.print_json(data=res)
            pause()
            return None

        quotas = res["data"].get("quotas", [])

        # --- DEBUG HOOK (sementara) ---
        # Untuk menyalakan debug: export DEBUG_QUOTAS=1  (Linux/macOS)
        # atau set DEBUG_QUOTAS=1 (Windows CMD / Powershell)
        # Jika aktif, akan menampilkan response/res["data"] dan contoh quota[0],
        # lalu berhenti sejenak agar Anda bisa melihat struktur JSON yang dikembalikan API.
        debug_enabled = os.environ.get("DEBUG_QUOTAS", "0") == "1"
        if debug_enabled:
            console.print("[info]DEBUG: full response 'data' object from quota-details[/]")
            try:
                console.print_json(data=res.get("data", {}))
            except Exception:
                console.print(f"[warning]Unable to pretty-print full data. Raw: {res.get('data')}[/]")
            console.print("[info]DEBUG: sample quota (first item) if available[/]")
            if quotas:
                try:
                    console.print_json(data=quotas[0])
                except Exception:
                    console.print(f"[warning]Unable to pretty-print quota[0]. Raw: {quotas[0]}[/]")
            else:
                console.print("[info]DEBUG: quotas list is empty[/]")
            pause()
        # --- END DEBUG HOOK ---

        clear_screen()

        # --- Paket Aktif header ---
        try:
            active_user = AuthInstance.get_active_user() or {}
            account_number = active_user.get("number", "N/A")
            account_name = active_user.get("name", "") or active_user.get("account_name", "") or ""
        except Exception:
            account_number = "N/A"
            account_name = ""

        # compute overall DATA quota summary and render centered bar (now bar uses remaining/total)
        remaining_bytes, total_bytes = _compute_quotas_summary(quotas)
        if total_bytes > 0:
            numbers = f"{format_quota_byte(remaining_bytes)} / {format_quota_byte(total_bytes)}"
            overall_bar = _render_progress_bar(remaining_bytes, total_bytes, width=_get_bar_width())
        else:
            numbers = "[orange1]Tuku paket ndisek🤪[/orange1]"
            overall_bar = _render_progress_bar(0, 1, width=_get_bar_width())

        header_table = Table.grid(expand=True)
        header_table.add_row(Align(f"[neon_yellow]📦 Paket Aktif[/]", align="center"))
        header_table.add_row(Align(f"[neon_green]Akun aktif: {account_number}[/]", align="center"))
        if account_name:
            header_table.add_row(Align(f"[bold]{account_name}[/]", align="center"))
        header_table.add_row(Align(f"[neon_cyan]Kuota:[/] {numbers}", align="center"))
        header_table.add_row(Align(overall_bar, align="center"))
        print_cyber_panel(header_table, title="")

        my_packages = []
        num = 1

        # If quotas list empty
        if not quotas:
            console.print("[warning]No packages found.[/]")
            pause()
            return None

        # Show detailed panels for each quota
        for quota in quotas:
            quota_code = quota.get("quota_code", "")
            quota_name = quota.get("name", "")
            product_subscription_type = quota.get("product_subscription_type", "")
            product_domain = quota.get("product_domain", "")

            group_code = quota.get("group_code", quota.get("package_group_code", ""))

            # try multiple possible locations for timestamps (to make sure we display them)
            active_since = (
                quota.get("activated_at")
                or quota.get("active_since")
                or quota.get("package_option", {}).get("activated_at")
                or quota.get("package_option", {}).get("active_since")
                or quota.get("package", {}).get("activated_at")
                or quota.get("package", {}).get("active_since")
            )
            reset_at = (
                quota.get("reset_at")
                or quota.get("reset_quota_at")
                or quota.get("package_option", {}).get("reset_at")
                or quota.get("package_option", {}).get("reset_quota_at")
                or quota.get("package", {}).get("reset_at")
                or quota.get("package", {}).get("reset_quota_at")
            )

            detail_tbl = Table(show_header=False, box=None, padding=(0,1))
            detail_tbl.add_column("Key", style="neon_cyan", justify="right")
            detail_tbl.add_column("Value", style="bold white")

            detail_tbl.add_row("Nama:", quota_name)
            detail_tbl.add_row("Quota Code:", f"[neon_yellow]{quota_code}[/]")
            if group_code:
                detail_tbl.add_row("Group Code:", group_code)
            if active_since:
                detail_tbl.add_row("Masa Aktif Kuota:", _format_ts(active_since))
            if reset_at:
                days_left = _days_until(reset_at)
                if days_left is not None:
                    detail_tbl.add_row("Reset Kuota:", f"{_format_ts(reset_at)} (sisa {days_left} hari)")
                else:
                    detail_tbl.add_row("Reset Kuota:", _format_ts(reset_at))

            benefits = quota.get("benefits", [])
            benefit_table = Table(show_header=True, header_style="neon_pink", box=None, padding=(0,1))
            benefit_table.add_column("Nama", style="white", width=25)
            benefit_table.add_column("Jenis", style="dim", width=12)
            benefit_table.add_column("Kuota", style="bold white", width=20)

            bar_width = _get_bar_width()

            if not benefits:
                benefit_table.add_row("Main Quota", "", "No benefits")
            else:
                for b in benefits:
                    bname = b.get("name", "Benefit")
                    dtype = b.get("data_type", "")
                    remaining = int(b.get("remaining", b.get("total", 0)) or 0)
                    total = int(b.get("total", 0) or 0)

                    if dtype == "DATA":
                        kuota_numbers = f"{format_quota_byte(remaining)} / {format_quota_byte(total)}"
                    elif dtype == "VOICE":
                        kuota_numbers = f"{remaining/60:.2f}m / {total/60:.2f}m"
                    elif dtype == "TEXT":
                        kuota_numbers = f"{remaining} / {total} SMS"
                    else:
                        kuota_numbers = f"{remaining} / {total}"

                    if b.get("is_unlimited", False) or total == 0:
                        bar = _render_progress_bar(0, 1, width=bar_width)
                        if b.get("is_unlimited", False):
                            kuota_numbers = "Unlimited"
                    else:
                        bar = _render_progress_bar(remaining, total, width=bar_width)

                    kuota_cell = f"{kuota_numbers}\n{bar}"
                    benefit_table.add_row(bname, dtype, kuota_cell)

            print_cyber_panel(detail_tbl, title=f"PAKET {num}")
            print_cyber_panel(benefit_table, title="RINCIAN KUOTA")

            my_packages.append({
                "number": num,
                "name": quota_name,
                "quota_code": quota_code,
                "product_subscription_type": product_subscription_type,
                "product_domain": product_domain,
                "full_data": quota
            })
            num += 1

        console.print(Panel(
            """[bold white]Input Number[/]: View Detail
[bold white]del <N>[/]: Unsubscribe
[bold white]00[/]: Back to Main Menu""",
            title="ACTIONS",
            border_style="neon_cyan"
        ))

        choice = cyber_input("Choice")
        if choice == "00":
            in_my_packages_menu = False

        if choice.isdigit() and int(choice) > 0 and int(choice) <= len(my_packages):
            selected_pkg = next((pkg for pkg in my_packages if pkg["number"] == int(choice)), None)
            if not selected_pkg:
                console.print("[error]Paket tidak ditemukan. Silakan masukan nomor yang benar.[/]")
                pause()
                continue

            _ = show_package_details(api_key, tokens, selected_pkg["quota_code"], False)

        elif choice.startswith("del "):
            del_parts = choice.split(" ")
            if len(del_parts) != 2 or not del_parts[1].isdigit():
                console.print("[error]Invalid input for delete command.[/]")
                pause()
                continue

            del_number = int(del_parts[1])
            del_pkg = next((pkg for pkg in my_packages if pkg["number"] == del_number), None)
            if not del_pkg:
                console.print("[error]Package not found for deletion.[/]")
                pause()
                continue

            confirm = cyber_input(f"Are you sure you want to unsubscribe from package  {del_number}. {del_pkg['name']}? (y/n)")
            if confirm.lower() == 'y':
                with loading_animation(f"Unsubscribing from {del_pkg['name']}..."):
                    success = unsubscribe(
                        api_key,
                        tokens,
                        del_pkg["quota_code"],
                        del_pkg["product_subscription_type"],
                        del_pkg["product_domain"]
                    )
                if success:
                    console.print("[neon_green]Successfully unsubscribed from the package.[/]")
                else:
                    console.print("[error]Failed to unsubscribe from the package.[/]")
            else:
                console.print("[warning]Unsubscribe cancelled.[/]")
            pause()
