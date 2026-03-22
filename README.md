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

## Jak spustit lokálně
1. Nainstalujte závislosti:
   ```bash
   npm install
   ```
2. Spusťte vývojový server:
   ```bash
   npm run dev
   ```
3. Aplikace bude dostupná na `http://localhost:3000`.

## Propojení s démonem
Tento projekt je připraven pro komunikaci s `sysext-creator-daemon` přes Varlink protokol. V souboru `server.ts` je připraveno API, které stačí propojit se skutečným unix socketem `/run/sysext-creator/sysext-creator.sock`.
