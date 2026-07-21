# Energy Planner pro Home Assistant

[English](README.md) | Česky

Energy Planner pomáhá uživatelům Home Assistantu odhadnout, co se bude dít s
domácí baterií během dalšího dne. Kombinuje nedávnou spotřebu domu, volitelné
řízené spotřebiče a Solcast předpověď FVE, která už existuje v Home Assistantu.

> [!WARNING]
> Energy Planner je experimentální software v aktivním vývoji. Není doporučený
> pro produkční použití. Instalaci a používání provádíte na vlastní riziko.
> Nespoléhejte se na něj pro bezpečnostní, životně důležitá, majetková,
> havarijní, provozní, finanční, fakturační, regulatorní ani compliance
> rozhodnutí.

Energy Planner **sám nic neovládá**. Pouze vytváří senzory a binární senzory,
které můžete použít v dashboardech nebo ve vlastních automatizacích.

## S čím pomůže

- Ukáže predikci SoC baterie na dalších 24 hodin nebo déle.
- Pomůže rozhodnout, jestli má smysl baterii nabíjet v nízkém tarifu.
- Ukáže, jestli je podle plánu ještě povolené vybíjení baterie.
- Odhadne nevyužitý přebytek z FVE pro bojler, bazén, ohřev vody nebo EV.
- Doporučí rozdělení úplně pokrytého zítřejšího přebytku mezi řízené spotřebiče
  podle jejich nedávné denní spotřeby nebo volitelné entity s požadavkem.
- Oddělí řízené spotřebiče od běžné spotřeby domu, aby se lépe učil běžný
  profil domácnosti.
- Ukáže řízené spotřebiče zvlášť, takže uvidíte spotřebu EV, TUV, bazénu nebo
  jiné řízené zátěže samostatně.

Například u tarifu D25d můžete v létě využít přebytek z FVE pro pružné
spotřebiče a v zimě lépe plánovat využití nízkého tarifu tak, aby baterie
překlenula vysoký tarif.

## Instalace

Je vyžadován Home Assistant 2025.3 nebo novější.

### HACS

1. Přidejte `https://github.com/ara686/ha-energy-planner` jako **Integration**
   custom repository v HACS.
2. Nainstalujte **Energy Planner**.
3. Restartujte Home Assistant.
4. Přidejte **Energy Planner** přes **Nastavení > Zařízení a služby**.

### Ruční instalace

1. Zkopírujte `custom_components/energy_planner` do adresáře
   `custom_components` ve vašem Home Assistantu.
2. Restartujte Home Assistant.
3. Přidejte integraci z UI.

YAML konfigurace není podporovaná.

## Co připravit před nastavením

Energy Planner se nastavuje v UI Home Assistantu. Během nastavení vyberete
existující HA entity.

Povinné:

- SoC baterie v `%`.
- Kapacita baterie v `kWh`.
- Minimální nebo rezervní SoC baterie v `%`.
- Kumulativní spotřeba celého domu v `kWh`.

Volitelné:

- Jedna nebo více kumulativních entit řízené spotřeby v `kWh`, například EV,
  bojler, ohřev vody nebo bazénová technologie.
- Volitelná číselná entita v `kWh` pro každý řízený odběr s energií požadovanou
  na zítřek. Pro daný odběr přepíše historický odhad.
- Solcast předpověď FVE pro dnešek, zítřek a další dny.

Pokud máte spotřebu domu jen jako okamžitý výkon, například
`sensor.home_power` ve `W`, vytvořte nejdřív v Home Assistantu helper
**Integral** a v Energy Planneru použijte výsledný `kWh` senzor.

Podrobný seznam vstupů, jednotek a provozních možností je v
[detailní konfiguraci](docs/configuration.md).

## První výsledky

Energy Planner staví hodinový profil spotřeby z historie Home Assistantu.

- Pokud Home Assistant už má historii vybraných energetických senzorů, rozumné
  hodnoty se mohou objevit hned.
- U nové instalace bez historie počítejte s prvními rozumnými výsledky zhruba po
  24 hodinách.
- Přesnější hodnoty čekejte zhruba po 48 hodinách, protože planner uvidí stejné
  hodiny dne vícekrát.
- Doporučení pro řízené odběry vyžaduje alespoň tři dostatečně pokryté ukončené
  dny. Běžný odhad používá až sedm posledních dní.

Reconfigure uloženou historii zachovává. Pokud změníte zdrojovou entitu,
výsledky chvíli sledujte. Integraci smažte jen tehdy, když chcete záměrně
smazat i uloženou historii planneru.

## Hlavní entity pro použití

Skutečná entity ID se mohou lišit, pokud Home Assistant přidá suffix nebo pokud
entity ručně přejmenujete. Zkontrolujte je v **Nastavení > Zařízení a služby >
Energy Planner > Entity**.

Nejužitečnější entity:

| Entita | Význam |
|--------|--------|
| `sensor.energy_planner_soc_forecast` | Pasivně predikované SoC na konci nastaveného horizontu. Používá aktuální SoC, historii spotřeby a předpověď FVE, bez předpokladu, že automatizace Energy Planneru už baterii nabila nebo zamkla. V atributech obsahuje body pro graf. |
| `sensor.energy_planner_soc_forecast_24h` | Pasivně predikované SoC přesně za 24 hodin od posledního výpočtu. |
| `binary_sensor.energy_planner_charge_now` | Zapnuto, když plán říká, že teď má smysl nabíjet. |
| `binary_sensor.energy_planner_discharge_allowed` | Zapnuto, když plán povoluje vybíjení baterie. |
| `sensor.energy_planner_target_soc` | Cílové SoC použité plannerem. |
| `sensor.energy_planner_charge_to_soc` | SoC potřebné pro plánované nabíjení ze sítě. |
| `sensor.energy_planner_safe_discharge_soc` | Nejnižší SoC, které ještě zachová plán. |
| `sensor.energy_planner_unused_surplus_today` | Odhad nevyužitého přebytku z FVE pro dnešek z pasivní predikce. |
| `sensor.energy_planner_unused_surplus_tomorrow` | Rozdělitelný přebytek na zítřek. Hodnotu má jen při pokrytí celého místního dne i solárních vstupů. |
| `sensor.energy_planner_recommended_managed_energy_tomorrow` | Celková energie doporučená pro všechny řízené odběry na zítřek. |
| `sensor.energy_planner_unallocated_surplus_tomorrow` | Zítřejší přebytek zbývající po všech doporučeních. |
| `sensor.energy_planner_managed_<source>_suggested_tomorrow` | Doporučená energie pro jeden odběr; atributy obsahují metodu, spolehlivost a historické vstupy. |
| `sensor.energy_planner_managed_<source>_today` | Dnešní spotřeba jedné řízené zátěže, například EV nebo TUV. |
| `sensor.energy_planner_managed_<source>_tracked_total` | Sledovaný součet Energy Planneru pro jednu řízenou zátěž. |

Kompletní seznam entit je v [přehledu entit](docs/entities.md).

## Dashboardy

Dobré první dashboardy:

- Graf budoucího SoC z `sensor.energy_planner_soc_forecast`.
- Gauge s hodnotou SoC za 24 hodin z `sensor.energy_planner_soc_forecast_24h`.
- Graf nevyužitého přebytku FVE.
- Graf spotřeby domu proti řízené spotřebě.
- Graf řízených spotřebičů zvlášť, například EV a TUV jako samostatné řady.

Lovelace a ApexCharts ukázky jsou v [dashboard příkladech](docs/dashboard.md).
Screenshoty se dají později doplnit tam, bez zbytečného natahování hlavního
README.

## Nápady na automatizace

Energy Planner zařízení přímo neovládá, ale vytváří jednoduché signály pro vaše
automatizace:

- `binary_sensor.energy_planner_charge_now` pro povolení nabíjení ze sítě.
- `binary_sensor.energy_planner_discharge_allowed` pro povolení vybíjení.
- `sensor.energy_planner_unused_surplus_today` pro spuštění pružných spotřebičů,
  když je dost předpokládaného přebytku z FVE.
- Hodnotu každého `managed_<source>_suggested_tomorrow` jako vstup vlastní
  automatizace na další den; Energy Planner zařízení stále sám nespíná.
- Per-load managed senzory pro prioritizaci spotřebičů, například nejdřív
  dohřát TUV a teprve potom povolit nabíjení EV.

Příklady automatizací s placeholdery jsou v
[příkladech automatizací](docs/automations.md). Automatizace vždy nejdřív ručně
otestujte ve vlastním Home Assistantu.

## Ruční přepočet

Energy Planner se přepočítává automaticky a reaguje také na změny SoC baterie.

Ruční přepočet spustíte přes **Developer Tools > Services**:

```text
energy_planner.recalculate
```

## Troubleshooting

- `insufficient_data` obvykle znamená, že povinná zdrojová entita chybí, je
  unavailable nebo není číselná.
- Pokud je spotřeba domu ve `W`, převeďte ji přes Integral helper na `kWh`.
- `warning` obvykle znamená, že nakonfigurovaný volitelný zdroj, například
  vybraná Solcast entita, chybí nebo nemá použitelnou předpověď.
- Pokud jsou grafy prázdné, zkontrolujte v **Developer Tools > States**, že
  `sensor.energy_planner_soc_forecast` má atribut `points`.
- Pokud hodnoty po první instalaci vypadají zvláštně, počkejte alespoň 24 až 48
  hodin na historii.

Diagnostiku najdete na stránce integrace. Pomůže zkontrolovat nastavené entity,
aktivní možnosti, warnings a poslední výstup planneru.

## Odstranění

1. Otevřete **Nastavení > Zařízení a služby > Energy Planner**.
2. Smažte integrační položku.
3. Pokud jste instalovali přes HACS, odeberte Energy Planner i v HACS.
4. Restartujte Home Assistant, pokud si o to řekne.

Smazání integrační položky odstraní uloženou interní historii Energy Planneru.
Nesmaže vaše původní zdrojové entity, helpery, dashboardy ani automatizace.

## Další dokumentace

- [Detailní konfigurace](docs/configuration.md)
- [Všechny vytvořené entity](docs/entities.md)
- [Dashboard příklady](docs/dashboard.md)
- [Příklady automatizací](docs/automations.md)
- [Jak funguje historie](docs/history.md)
- [Detaily planneru](docs/planner.md)
