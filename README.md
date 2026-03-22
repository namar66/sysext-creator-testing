# Sysext Manager Dashboard

Moderní grafické rozhraní pro správu systémových rozšíření (systemd-sysext) na Fedora Atomic Desktop.

## Funkce
- **Extensions**: Přehled nainstalovaných rozšíření.
- **Update**: Kontrola a instalace aktualizací pro jednotlivé sysext balíčky.
- **Search**: Vyhledávání balíčků v Fedora repozitářích.
- **Doctor**: Diagnostika zdraví systému a spojení s démonem.

## Technologie
- **Frontend**: React, Tailwind CSS, Lucide Icons, Motion.
- **Backend**: Express.js (slouží jako API bridge k Varlink socketu).

## Python Nástroje (Lokální)
Kromě webového rozhraní projekt obsahuje sadu Python skriptů pro přímou správu na hostitelském systému:

- **`sysext-gui.py`**: Hlavní grafické rozhraní (PyQt6) s taby pro správu, tvorbu, vyhledávání a diagnostiku.
- **`sysext-daemon.py`**: Varlink démon, který běží na pozadí a provádí operace s právy roota.
- **`sysext-builder.py`**: Skript běžící uvnitř toolboxu, který vytváří `.raw` obrazy z RPM balíčků.
- **`sysext-cli.py`**: Příkazová řádka pro rychlou instalaci a správu rozšíření.
- **`sysext-doctor.py`**: Diagnostický nástroj pro kontrolu kolizí v `/etc` a RPM databázi.
- **`sysext-updater.py`**: Automatický updater, který hlídá nové verze balíčků v repozitářích.
- **`sysext-test.py`**: Testovací sada pro ověření funkčnosti celého řetězce.

## Jak spustit lokální GUI
```bash
# Ujistěte se, že máte nainstalované PyQt6 a varlink
python3 sysext-gui.py
```
