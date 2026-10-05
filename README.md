# Amazon Preisalarm für Home Assistant

Überwacht beliebig viele Amazon-Produkte und meldet, wie sich der Preis seit dem
Hinzufügen (bzw. seit dem letzten Zurücksetzen) verändert hat.

## Funktionen

- Beliebig viele Produkte per UI hinzufügen (auch Kurzlinks wie `amzn.eu/d/…`)
- Alle Amazon-Marktplätze (amazon.de, .com, .co.uk, .fr, …), Währung wird automatisch erkannt
- Einstellbares Abfrageintervall (Standard 60 min, mindestens 15 min)
- Pro Produkt ein Gerät mit diesen Entitäten:

| Entität | Beschreibung |
|---|---|
| `sensor.<produkt>_preis` | Aktueller Preis (Attribute: Titel, ASIN, Link, Verfügbarkeit, Referenzpreis, Fehler, …) |
| `sensor.<produkt>_preisanderung` | Aktueller Preis − Referenzpreis, z. B. `-12.5` (günstiger) oder `5.0` (teurer). Attribut `change_formatted` liefert `-12,50 €` / `+5,00 €`, Attribut `trend` liefert `up`/`down`/`unchanged` |
| `sensor.<produkt>_preisanderung_prozent` | Änderung in % |
| `binary_sensor.<produkt>_zielpreis_erreicht` | Nur wenn ein Zielpreis gesetzt ist: `on`, sobald Preis ≤ Zielpreis |
| `button.<produkt>_referenzpreis_zurucksetzen` | Setzt den aktuellen Preis als neuen Referenzpreis |

Der **Referenzpreis** ist der Preis zum Zeitpunkt des Hinzufügens. Er bleibt über
Neustarts erhalten und ändert sich nur über den Button.

## Installation

### HACS (Custom Repository)
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repos, Typ *Integration*
2. „Amazon Preisalarm“ installieren, Home Assistant neu starten

### Manuell
Ordner `custom_components/amazon_preisalarm` nach `<config>/custom_components/` kopieren
und Home Assistant neu starten.

Voraussetzung: Home Assistant **2025.4** oder neuer.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → Amazon Preisalarm*
2. Abfrageintervall festlegen
3. Beim Integrationseintrag auf **„Produkt hinzufügen“** klicken, Amazon-Link einfügen,
   optional Name und Zielpreis angeben
4. Name/Zielpreis lassen sich später über das ⋮-Menü des Produkts ändern,
   das Intervall über *Konfigurieren*

## Event für Automationen

Bei jeder Preisänderung (gegenüber der letzten Abfrage) wird das Event
`amazon_preisalarm_price_changed` ausgelöst:

```yaml
name: Toller Kopfhörer
title: <voller Produkttitel>
asin: B0XXXXXXXX
url: https://www.amazon.de/dp/B0XXXXXXXX
currency: EUR
old_price: 89.99
new_price: 79.99
reference_price: 99.99
change: -20.0
change_percent: -20.0
direction: down
target_price: 80.0
target_reached: true
```

Beispiel-Automation (Push bei Preissenkung):

```yaml
automation:
  - alias: Amazon Preis gesunken
    triggers:
      - trigger: event
        event_type: amazon_preisalarm_price_changed
        event_data:
          direction: down
    actions:
      - action: notify.mobile_app_mein_handy
        data:
          title: "Preis gesunken: {{ trigger.event.data.name }}"
          message: >
            {{ trigger.event.data.old_price }} → {{ trigger.event.data.new_price }}
            {{ trigger.event.data.currency }}
            ({{ trigger.event.data.change }} seit Hinzufügen)
          data:
            url: "{{ trigger.event.data.url }}"
```

## Hinweise / Grenzen

- Die Preise werden per HTML-Scraping ermittelt. Amazon antwortet gelegentlich mit
  einem Captcha. Dann wird die Abfrage abgebrochen, die letzten bekannten Werte bleiben
  erhalten und im nächsten Intervall wird es erneut versucht.
  Zwischen den Produkten wird jeweils 2–5 s gewartet.
- Der Preis entspricht dem Preis der Buy-Box (Hauptangebot) der jeweiligen Produktvariante.
- Ist ein Produkt nicht verfügbar, ist der Preis `unbekannt`.

## Entwicklung

```bash
pip install beautifulsoup4 aiohttp pytest
pytest tests
```
