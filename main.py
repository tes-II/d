from dotenv import load_dotenv
load_dotenv()

import sys, json, os
from datetime import datetime
from app.menus.util import clear_screen, pause, format_quota_byte
from app.client.engsel import (
    get_balance,
    get_tiering_info,
    send_api_request,
)
from app.client.famplan import validate_msisdn
from app.menus.payment import show_transaction_history
from app.service.auth import AuthInstance
from app.menus.bookmark import show_bookmark_menu
from app.service.bookmark import BookmarkInstance
from app.menus.account import show_account_menu
from app.menus.package import fetch_my_packages, get_packages_by_family, show_package_details
from app.menus.hot import show_hot_menu, show_hot_menu2, show_hot_menu3
from app.service.sentry import enter_sentry_mode
from app.menus.purchase import purchase_by_family
from app.menus.famplan import show_family_info
from app.menus.circle import show_circle_info
from app.menus.notification import show_notification_menu
from app.menus.store.segments import show_store_segments_menu
from app.menus.store.search import show_family_list_menu, show_store_packages_menu
from app.menus.store.redemables import show_redeemables_menu
from app.client.registration import dukcapil
#from app.client.sharing import bounty_allotment_menu

from rich.table import Table
from rich.columns import Columns
from rich.panel import Panel
from rich.align import Align
from app.console import console, print_cyber_panel, cyber_input, loading_animation, print_step

WIDTH = 55

def _get_bar_width_for_profile(min_w: int = 12, max_w: int = 60, reserved: int = 40) -> int:
    try:
        total = console.size.width or 80
        avail = max(10, total - reserved)
        return max(min_w, min(max_w, avail))
    except Exception:
        return min_w

# def _render_progress_bar(used: int, total: #int, width: int = 30, fill_char: str = "▒", #empty_char: str = "░"):
#    try:
#        if not isinstance(total, (int, float)) #or total <= 0:
#            bar = empty_char * width
#            return f"[dim]{bar}[/] N/A"
#        used_clamped = max(0, min(used, total))
#        frac = used_clamped / total
#        filled = int(round(frac * width))
#        filled_part = fill_char * filled
#        empty_part = empty_char * (width - filled)
#        pct = int(round(frac * 100))
#        if pct >= 50:
#            color = "neon_green"
#        elif pct >= 30:
#            color = "orange1"
#        else:
#            color = "red"
#        return f"[{color}]{filled_part}[/][dim]{empty_part}[/] {pct}%"
#    except Exception:
#        bar = empty_char * width
#        return f"[dim]{bar}[/] 0%"

def _render_profile_bar(remaining: int, total: int, width: int = 30, fill_char: str = "▒", empty_char: str = "░"):
    """
    Render profile bar based on remaining/total (SISA kuota).
    Color thresholds (based on remaining %):
      >=100% => neon_green
      >=55%  => orange1
      >=20%  => red
      <20%   => red
    """
    try:
        if not isinstance(total, (int, float)) or total <= 0:
            bar = empty_char * width
            return f"[dim]{bar}[/] N/A"
        remaining_clamped = max(0, min(remaining, total))
        frac = remaining_clamped / total
        filled = int(round(frac * width))
        filled_part = fill_char * filled
        empty_part = empty_char * (width - filled)
        pct = int(round(frac * 100))

        # color selection per your request
        if pct >= 100:
            color = "neon_green"
        elif pct >= 56:
            color = "neon_green"
        elif pct >= 20:
            color = "orange1"
        elif pct >= 55:
            color = "red"
        else:
            color = "red"

        return f"[{color}]{filled_part}[/][dim]{empty_part}[/] {pct}%"
    except Exception:
        bar = empty_char * width
        return f"[dim]{bar}[/] 0%"

def _get_quotas_summary(api_key, tokens):
    try:
        id_token = tokens.get("id_token")
        path = "api/v8/packages/quota-details"
        payload = {"is_enterprise": False, "lang": "en", "family_member_id": ""}
        res = send_api_request(api_key, path, payload, id_token, "POST")
        if res.get("status") != "SUCCESS":
            return None
        quotas = res["data"].get("quotas", [])
        total = 0
        remaining = 0
        for q in quotas:
            for b in q.get("benefits", []):
                if b.get("data_type") == "DATA":
                    t = int(b.get("total") or 0)
                    r = int(b.get("remaining") or 0)
                    total += t
                    remaining += r
        return (remaining, total)
    except Exception:
        return None

def show_main_menu(profile):
    clear_screen()

    expired_at_dt = datetime.fromtimestamp(profile["balance_expired_at"]).strftime("%d-%m-%Y")

    profile_table = Table(show_header=False, box=None, padding=(0, 1))
    profile_table.add_column("Key", style="neon_cyan", justify="right")
    profile_table.add_column("Value", style="bold white")

    profile_table.add_row("Nomor:", str(profile['number']))
    profile_table.add_row("Nama:", str(profile.get('account_name', 'N/A')))
    profile_table.add_row("Type:", str(profile['subscription_type']))
    profile_table.add_row("Pulsa:", f"Rp {profile['balance']}")
    profile_table.add_row("Aktif s/d:", str(expired_at_dt))
    profile_table.add_row("Info:", str(profile['point_info']))

    # Sisa semua kuota: angka (baris 1) + bar flex di baris 2 (menggunakan remaining%)
    try:
        api_key = AuthInstance.api_key
        tokens = AuthInstance.get_active_tokens()
        if tokens:
            qsum = _get_quotas_summary(api_key, tokens)
            if qsum:
                remaining_bytes, total_bytes = qsum
                if total_bytes > 0:
                    formatted_numbers = f"{format_quota_byte(remaining_bytes)} / {format_quota_byte(total_bytes)}"
                    profile_table.add_row("Kuota:", formatted_numbers)
                    # bar below (centered) using remaining%
                    bar_width = _get_bar_width_for_profile()
                    bar = _render_profile_bar(remaining_bytes, total_bytes, width=bar_width)
                    profile_table.add_row("", Align(bar, align="center"))
                else:
                    profile_table.add_row("Kuota:","[orange1]Tidak ada paket ❌[/orange1]")
    except Exception:
        # fail silently
        pass

    print_cyber_panel(profile_table, title="USER PROFILE")

    menu_table = Table(show_header=True, header_style="neon_pink", box=None, padding=(0, 1))
    menu_table.add_column("ID", style="neon_green", justify="right", width=4)
    menu_table.add_column("Action", style="bold white")

    menu_items = [
        ("1", "Login/Ganti akun"),
        ("2", "Lihat Paket Saya"),
        ("3", "Beli Paket [red] HOT [/red]"),
        ("4", "Beli Paket [red]HOT-2 [/red]"),
        ("5", "Keluarga [neon_pink]Biz[/neon_pink]"),
        #("6", "BIZ lite (BIZ ORI only )"),
        #("7", "BIZ Data+ (BIZ ORI only )"),
        ("6", "Beli Paket (Option Code)"),
        ("7", "Beli Paket (Family Code)"),
        ("8", "Beli Semua Paket (Loop)"),
        ("9", "Riwayat Transaksi"),
        ("10", "Family Plan/Akrab"),
        ("11", "Circle"),
        #("14", "Store Segments"),
        ("12", "Store Family List"),
        #("16", "Store Packages"),
        ("13", "Redemables"),
        #("S", "Biz Stat"),
        ("R", "Register Dukcapil"),
        ("N", "Notifikasi"),
        ("V", "Validate MSISDN"),
        ("00", "Bookmark Paket"),
        ("99", "Tutup Aplikasi"),
    ]

    for key, desc in menu_items:
        menu_table.add_row(key, desc)

    console.print(Panel(menu_table, title="[neon_green]MAIN MENU[/]", border_style="bold red"))


show_menu = True
def main():
    while True:
        active_user = AuthInstance.get_active_user()

        if active_user is not None:
            with loading_animation("Fetching user data..."):
                balance = get_balance(AuthInstance.api_key, active_user["tokens"]["id_token"])
                balance_remaining = balance.get("remaining")
                balance_expired_at = balance.get("expired_at")

                point_info = "Points: N/A | Tier: N/A"
                if active_user["subscription_type"] == "PREPAID":
                    tiering_data = get_tiering_info(AuthInstance.api_key, active_user["tokens"])
                    tier = tiering_data.get("tier", 0)
                    current_point = tiering_data.get("current_point", 0)
                    point_info = f"Points: {current_point} | Tier: {tier}"

            account_name = ""
            try:
                account_name = active_user.get("name", "") or ""
            except Exception:
                account_name = ""

            profile = {
                "number": active_user["number"],
                "subscriber_id": active_user["subscriber_id"],
                "subscription_type": active_user["subscription_type"],
                "balance": balance_remaining,
                "balance_expired_at": balance_expired_at,
                "point_info": point_info,
                "account_name": account_name
            }

            show_main_menu(profile)

            choice = cyber_input("Pilih menu")

            if choice.lower() == "t":
                pause()
            elif choice == "1":
                selected_user_number = show_account_menu()
                if selected_user_number:
                    AuthInstance.set_active_user(selected_user_number)
                else:
                    console.print("[error]No user selected or failed to load user.[/]")
                    pause()
                continue
            elif choice == "2":
                fetch_my_packages()
                continue
            elif choice == "3":
                show_hot_menu()
            elif choice == "4":
                show_hot_menu2()
            elif choice == "5":
                show_hot_menu3()
            #elif choice == "s":
                #get_packages_by_family("20342db0-e03e-4dfd-b2d0-cd315d7ddc36")  
            #elif choice == "6":
                #get_packages_by_family("f3303d95-8454-4e80-bb25-38513d358a11")
            #elif choice == "7":
                #get_packages_by_family("53de8ac3-521d-43f5-98ce-749ad0481709")

            elif choice == "6":
                option_code = cyber_input("Enter option code (or '99' to cancel)")
                if option_code == "99":
                    continue
                show_package_details(
                    AuthInstance.api_key,
                    active_user["tokens"],
                    option_code,
                    False
                )
            elif choice == "7":
                family_code = cyber_input("Enter family code (or '99' to cancel)")
                if family_code == "99":
                    continue
                get_packages_by_family(family_code)
            elif choice == "8":
                family_code = cyber_input("Enter family code (or '99' to cancel)")
                if family_code == "99":
                    continue

                start_from_option = cyber_input("Start purchasing from option number (default 1)")
                try:
                    start_from_option = int(start_from_option)
                except ValueError:
                    start_from_option = 1

                use_decoy = cyber_input("Use decoy package? (y/n)").lower() == 'y'
                pause_on_success = cyber_input("Pause on each successful purchase? (y/n)").lower() == 'y'
                delay_seconds = cyber_input("Delay seconds between purchases (0 for no delay)")
                try:
                    delay_seconds = int(delay_seconds)
                except ValueError:
                    delay_seconds = 0
                purchase_by_family(
                    family_code,
                    use_decoy,
                    pause_on_success,
                    delay_seconds,
                    start_from_option
                )
            elif choice == "9":
                show_transaction_history(AuthInstance.api_key, active_user["tokens"])
            elif choice == "10":
                show_family_info(AuthInstance.api_key, active_user["tokens"])
            elif choice == "11":
                show_circle_info(AuthInstance.api_key, active_user["tokens"])
            elif choice == "12":
                input_11 = cyber_input("Is enterprise store? (y/n)").lower()
                is_enterprise = input_11 == 'y'
                show_store_segments_menu(is_enterprise)
            elif choice == "13":
                input_12_1 = cyber_input("Is enterprise? (y/n)").lower()
                is_enterprise = input_12_1 == 'y'
                show_family_list_menu(profile['subscription_type'], is_enterprise)
            #elif choice == "14":
                input_13_1 = cyber_input("Is enterprise? (y/n)").lower()
                is_enterprise = input_13_1 == 'y'
                
                show_store_packages_menu(profile['subscription_type'], is_enterprise)
            #elif choice == "15":
                input_14_1 = cyber_input("Is enterprise? (y/n)").lower()
                is_enterprise = input_14_1 == 'y'            
                show_redeemables_menu(is_enterprise)
            elif choice == "00":
                show_bookmark_menu()
            elif choice == "99":
                console.print("[bold red]Exiting the application...[/]")
                sys.exit(0)
            elif choice.lower() == "r":
                msisdn = cyber_input("Enter msisdn (628xxxx)")
                nik = cyber_input("Enter NIK")
                kk = cyber_input("Enter KK")
                
                with loading_animation("Registering..."):
                    res = dukcapil(
                        AuthInstance.api_key,
                        msisdn,
                        kk,
                        nik,
                    )
                console.print_json(data=res)
                pause()
            elif choice.lower() == "v":
                msisdn = cyber_input("Enter the msisdn to validate (628xxxx)")
                with loading_animation("Validating..."):
                    res = validate_msisdn(
                        AuthInstance.api_key,
                        active_user["tokens"],
                        msisdn,
                    )
                console.print_json(data=res)
                pause()
            elif choice.lower() == "n":
                show_notification_menu()
            elif choice == "s":
                enter_sentry_mode()
            else:
                console.print("[error]Invalid choice. Please try again.[/]")
                pause()
        else:
            selected_user_number = show_account_menu()
            if selected_user_number:
                AuthInstance.set_active_user(selected_user_number)
            else:
                console.print("[error]No user selected or failed to load user.[/]")
                pause()

if __name__ == "__main__":
    try:
        print_step("Checking for updates...")
        with loading_animation("Checking git..."):
            from app.service.git import check_for_updates
            need_update = check_for_updates()
        if need_update:
            pause()
        main()
    except KeyboardInterrupt:
        console.print("\n[bold red]Exiting the application.[/]")
