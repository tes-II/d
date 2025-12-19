from app.client.ciam import get_otp, submit_otp
from app.menus.util import clear_screen, pause
from app.service.auth import AuthInstance
from app.console import console, print_cyber_panel, cyber_input, loading_animation, print_step
from rich.table import Table
from rich.panel import Panel

def show_login_menu():
    clear_screen()

    menu_text = """
    1. Request OTP
    2. Submit OTP
    99. Tutup aplikasi
    """
    print_cyber_panel(menu_text, title="LOGIN MENU")
    
def login_prompt(api_key: str):
    clear_screen()
    print_cyber_panel("Masukan nomor XL untuk login.\nFormat: 628xxxxxxxxxx", title="AUTHENTICATION REQUIRED")

    phone_number = cyber_input("Nomor XL")

    if not phone_number.startswith("628") or len(phone_number) < 10 or len(phone_number) > 14:
        console.print("[error]Nomor tidak valid. Pastikan nomor diawali dengan '628' dan memiliki panjang yang benar.[/]")
        return None, None

    try:
        with loading_animation("Requesting OTP..."):
            subscriber_id = get_otp(phone_number)

        if not subscriber_id:
            return None, None

        console.print("[neon_green]OTP Berhasil dikirim ke nomor Anda.[/]")
        
        try_count = 5
        while try_count > 0:
            console.print(f"[warning]Sisa percobaan: {try_count}[/]")
            otp = cyber_input("Masukkan OTP (6 digit)")
            if not otp.isdigit() or len(otp) != 6:
                console.print("[error]OTP tidak valid. Pastikan OTP terdiri dari 6 digit angka.[/]")
                continue
            
            with loading_animation("Verifying OTP..."):
                tokens = submit_otp(api_key, "SMS", phone_number, otp)

            if not tokens:
                console.print("[error]OTP salah. Silahkan coba lagi.[/]")
                try_count -= 1
                continue
            
            console.print("[bold neon_green]ACCESS GRANTED. Berhasil login![/]")
            return phone_number, tokens["refresh_token"]

        console.print("[error]Gagal login setelah beberapa percobaan. Silahkan coba lagi nanti.[/]")
        return None, None
    except Exception as e:
        console.print(f"[error]Gagal login: {e}[/]")
        return None, None

def show_account_menu():
    clear_screen()
    AuthInstance.load_tokens()
    users = AuthInstance.refresh_tokens
    active_user = AuthInstance.get_active_user()
        
    in_account_menu = True
    add_user = False
    while in_account_menu:
        clear_screen()

        if AuthInstance.get_active_user() is None or add_user:
            number, refresh_token = login_prompt(AuthInstance.api_key)
            if not refresh_token:
                console.print("[error]Gagal menambah akun. Silahkan coba lagi.[/]")
                pause()
                add_user = False # Reset add_user state
                continue
            
            # Ask for optional friendly name before adding, pass to add_refresh_token
            name_input = cyber_input("Masukkan nama untuk akun ini (opsional)")
            AuthInstance.add_refresh_token(int(number), refresh_token, name_input.strip())

            AuthInstance.load_tokens()
            users = AuthInstance.refresh_tokens
            active_user = AuthInstance.get_active_user()
            
            if add_user:
                add_user = False
            continue
        
        # User Table with requested order: No, Nama, Nomor, Type, Baru, Status
        table = Table(show_header=True, header_style="neon_pink", box=None, padding=(0, 1))
        table.add_column("No", style="neon_green", justify="right")
        table.add_column("Nama", style="bold white")
        table.add_column("Nomor", style="bold white")
        table.add_column("Type", style="cyan")
        # <-- Tambahkan kolom "Baru" supaya jumlah kolom sama dengan values di add_row
        
        # <-- Pastikan kolom Status ada dan justify center agar ACTIVE tampil center
        table.add_column("Status", style="neon_green", justify="center")

        if not users or len(users) == 0:
            console.print("[warning]Tidak ada akun tersimpan.[/]")
        else:
            for idx, user in enumerate(users):
                is_active = active_user and user["number"] == active_user["number"]
                active_marker = "[bold neon_green]Aktif[/]" if is_active else ""

                number = str(user.get("number", ""))
                name = user.get("name", "")  # Optional friendly name
                sub_type = user.get("subscription_type", "")

                # New marker comes from in-memory set in AuthInstance
                new_marker = "[bold neon_pink]NEW[/]" if user.get("number") in getattr(AuthInstance, "newly_added_numbers", set()) else ""

                # Pastikan jumlah nilai di add_row sama dengan jumlah kolom (6)
                table.add_row(str(idx + 1), name, number, sub_type, active_marker)

        print_cyber_panel(table, title="SAVED ACCOUNTS")
        
        console.print(Panel(
            """[bold white]0[/]: Tambah Akun
[bold white]1-N[/]: Ganti Akun (Pilih Nomor)
[bold white]del <N>[/]: Hapus Akun
[bold white]E <N>[/]: Tambah / Edit Nama Akun
[bold white]00[/]: Kembali ke menu utama""",
            title="COMMANDS",
            border_style="neon_pink"
        ))

        input_str = cyber_input("Pilihan")
        if input_str == "00":
            in_account_menu = False
            return active_user["number"] if active_user else None
        elif input_str == "0":
            add_user = True
            continue
        elif input_str.isdigit() and 1 <= int(input_str) <= len(users):
            selected_user = users[int(input_str) - 1]
            return selected_user['number']
        elif input_str.startswith("del "):
            parts = input_str.split()
            if len(parts) == 2 and parts[1].isdigit():
                del_index = int(parts[1])

                # Validasi indek dulu biar tidek error
                if not users or len(users) == 0:
                    console.print("[error]Tidak ada akun untuk dihapus.[/]")
                    pause()
                    continue

                if not (1 <= del_index <= len(users)):
                    console.print("[error]Nomor urut tidak valid. Tidak ada akun dengan nomor urut tersebut.[/]")
                    pause()
                    continue
                
                # Prevent deleting the active user here
                if active_user and users[del_index - 1]["number"] == active_user["number"]:
                    console.print("[error]Tidak dapat menghapus akun aktif. Silahkan ganti akun terlebih dahulu.[/]")
                    pause()
                    continue
                
                if 1 <= del_index <= len(users):
                    user_to_delete = users[del_index - 1]
                    confirm = cyber_input(f"Yakin ingin menghapus akun {user_to_delete['number']}? (y/n)")
                    if confirm.lower() == 'y':
                        AuthInstance.remove_refresh_token(user_to_delete["number"])
                        users = AuthInstance.refresh_tokens
                        active_user = AuthInstance.get_active_user()
                        console.print("[info]Akun berhasil dihapus.[/]")
                        pause()
                    else:
                        console.print("[info]Penghapusan akun dibatalkan.[/]")
                        pause()
                else:
                    console.print("[error]Nomor urut tidak valid.[/]")
                    pause()
            else:
                console.print("[error]Perintah tidak valid. Gunakan format: del <nomor urut>[/]")
                pause()
            continue
        elif input_str.startswith("e "):
            parts = input_str.split()
            if len(parts) == 2 and parts[1].isdigit():
                name_index = int(parts[1])
                if 1 <= name_index <= len(users):
                    user_entry = users[name_index - 1]
                    new_name = cyber_input(f"Masukkan nama baru untuk akun {user_entry['number']} (kosong = hapus nama)")
                    new_name = new_name.strip()
                    if new_name == "":
                        if "name" in user_entry:
                            del user_entry["name"]
                    else:
                        user_entry["name"] = new_name
                    AuthInstance.write_tokens_to_file()
                    AuthInstance.load_tokens()
                    users = AuthInstance.refresh_tokens
                    active_user = AuthInstance.get_active_user()
                    console.print("[info]Nama akun berhasil diperbarui.[/]")
                    pause()
                else:
                    console.print("[error]Nomor urut tidak valid.[/]")
                    pause()
            else:
                console.print("[error]Perintah tidak valid. Gunakan format: e <nomor urut>[/]")
                pause()
            continue
        else:
            console.print("[error]Input tidak valid. Silahkan coba lagi.[/]")
            pause()
            continue
