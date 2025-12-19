from datetime import datetime


def format_unix_date_with_diff(ts: int, mode: str = "future") -> str:
    if not ts or ts <= 0:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(ts)
        bulan = [
            "Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des"
        ]
        tanggal = f"{dt.day} {bulan[dt.month - 1]} {dt.year}"
        jam = dt.strftime("%H:%M:%S")

        now = datetime.now()
        delta = dt - now
        total_seconds = int(delta.total_seconds())

        if mode == "future":
            if total_seconds >= 0:
                if delta.days > 0:
                    return f"{tanggal} {jam} (sisa {delta.days} hari)"
                elif total_seconds >= 3600:
                    jam_sisa = total_seconds // 3600
                    return f"{tanggal} {jam} (sisa {jam_sisa} jam)"
                elif total_seconds >= 60:
                    menit_sisa = total_seconds // 60
                    return f"{tanggal} {jam} (sisa {menit_sisa} menit)"
                else:
                    return f"{tanggal} {jam} (sisa {total_seconds} detik)"
            else:
                return f"{tanggal} {jam}"  # sudah lewat
        else:  # mode == "past"
            if total_seconds < 0:
                if abs(delta.days) > 0:
                    return f"{tanggal} {jam} ({abs(delta.days)} hari yang lalu)"
                elif abs(total_seconds) >= 3600:
                    jam_lalu = abs(total_seconds) // 3600
                    return f"{tanggal} {jam} ({jam_lalu} jam yang lalu)"
                elif abs(total_seconds) >= 60:
                    menit_lalu = abs(total_seconds) // 60
                    return f"{tanggal} {jam} ({menit_lalu} menit yang lalu)"
                else:
                    return f"{tanggal} {jam} ({abs(total_seconds)} detik yang lalu)"
            else:
                return f"{tanggal} {jam}"
    except Exception:
        return str(ts)


if __name__ == '__main__':
    import argparse
    import time

    parser = argparse.ArgumentParser(description='Format a unix timestamp and show time difference relative to now.')
    parser.add_argument('timestamp', nargs='?', type=int, default=int(time.time()),
                        help='Unix timestamp to format (default: now)')
    parser.add_argument('--mode', choices=['future', 'past'], default='future',
                        help='Display remaining time (future) or elapsed time (past)')

    args = parser.parse_args()
    print(format_unix_date_with_diff(args.timestamp, args.mode))
