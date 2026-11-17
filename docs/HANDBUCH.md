# Baukasten – Handbuch

Der Baukasten ist ein Werkzeug, mit dem interne Web-Apps im Browser entstehen:
Daten festlegen, Seiten aus Bausteinen zusammenstellen, veröffentlichen. Wer
programmieren kann, ergänzt Logik in Python. Technisch ist der Baukasten eine
Django-Anwendung, die auf Kubernetes läuft.

Dieses Handbuch gibt es auch in der Oberfläche: oben rechts unter „Hilfe“.

## Wo fange ich an?

| Du willst … | Lies |
|---|---|
| eine fertige App benutzen | [1. Apps benutzen](#1-apps-benutzen), fünf Minuten |
| deine erste eigene App bauen | [Schnellstart](#schnellstart-deine-erste-app-in-15-minuten), dann [2. Apps bauen](#2-apps-bauen) |
| Daten aus einer Datenbank oder Databricks anzeigen | [Daten aus Datenbanken und Databricks](#daten-aus-datenbanken-und-databricks) |
| mit einem anderen Programm auf Daten zugreifen | [API](#api) und die API-Dokumentation in der Oberfläche |
| Logik programmieren | [Skripte](#skripte) und [3. Entwickeln](#3-entwickeln) |
| fertige Beispiele ansehen | [Beispiel-Apps](#beispiel-apps) |
| den Baukasten auf dem eigenen Rechner in Kubernetes ausprobieren | [Lokal mit Kubernetes](#lokal-mit-kubernetes-docker-desktop) |
| den Baukasten installieren oder betreiben | [4. Betreiben](#4-betreiben) |
| eine schnelle Antwort | [Häufige Fragen](#häufige-fragen) |

## Die Begriffe in einem Bild

```
Baukasten
└── App  „Inventar“                     ← eine Anwendung für einen Zweck
    ├── Tabellen   „Geräte“, „Räume“    ← welche Daten es gibt
    │   └── Felder  Bezeichnung, Preis …    ← was zu jedem Eintrag gehört
    │       └── Einträge  „Beamer“, „Oszilloskop“ …   ← die eigentlichen Daten
    ├── Seiten     „Übersicht“, „Geräte“ ← was Nutzer sehen
    │   └── Bausteine  Liste, Diagramm, Formular …
    ├── Skripte    Python oder JavaScript ← eigene Logik
    ├── Abfragen   SQL an Datenbanken    ← Daten von außen
    ├── API-Schlüssel                    ← Zugang für andere Programme
    └── Versionen                        ← gespeicherte Stände des Aufbaus
```

## Die vier Teile

| Teil | Für wen |
|---|---|
| [1. Apps benutzen](#1-apps-benutzen) | alle, die mit fertigen Apps arbeiten |
| [2. Apps bauen](#2-apps-bauen) | Designer: Fachabteilungen, die Apps anlegen |
| [3. Entwickeln](#3-entwickeln) | Entwickler: Skripte, Python-Erweiterungen, API, Python-Bibliothek, Aufbau des Codes |
| [4. Betreiben](#4-betreiben) | Betrieb: Installation, Kubernetes, Datenquellen, Keycloak, Sicherheit |

Am Ende stehen [Häufige Fragen](#häufige-fragen),
[Grenzen des jetzigen Stands](#grenzen-des-jetzigen-stands) und ein
[Glossar](#glossar).

---

## Beispiel-Apps

| App | Zeigt | Anlegen |
|---|---|---|
| Inventar | Tabellen, Formulare, Kennzahlen, Diagramme, Datenquelle, Python- und JavaScript-Skripte | `python manage.py demo` |
| Aufnahme-Einwilligung | Ablauf über mehrere Personen: Veranstaltung anlegen, Link verschicken, zustimmen oder ablehnen, Auswertung | `python manage.py beispiel_einwilligung` |

**Aufnahme-Einwilligung** im Einzelnen:

- Auf der Startseite „Veranstaltungen“ legt die verantwortliche Person eine
  Veranstaltung an: Titel, Datum, Ort, Art der Aufnahmen und Zweck.
- Das Skript „Teilnahme-Link erzeugen“ (nach dem Speichern) trägt den Link
  `/a/einwilligung/p/teilnahme/?event=<Nummer>` und die verantwortliche Person
  ein. Beide Felder stehen nicht im Formular.
- Die Seite „Teilnahme“ steht nicht im Menü. Ein Seitenskript liest die Nummer
  aus der Adresse und zeigt Titel, Datum, Aufnahmen, Zweck und die bisherige
  Antwort der angemeldeten Person.
- Die Buttons „Ich stimme den Aufnahmen zu“ und „Ich lehne ab“ starten je ein
  Python-Skript. Es speichert Name, E-Mail, Entscheidung und Zeitpunkt. Je
  Person und Veranstaltung gibt es genau eine Antwort; eine neue Antwort
  ersetzt die alte.
- **Gäste ohne Konto**, gebaut nur mit Baukasten-Funktionen: Das Skript
  „Teilnahme-Link erzeugen“ gibt jeder Veranstaltung mit `token()` einen
  geheimen Code und trägt den Gast-Link `/a/einwilligung/p/gast/?code=<Code>`
  ein. Die Seite „Gast“ ist eine [öffentliche Seite](#öffentliche-seiten) mit
  zwei Eingabefeldern (Name, E-Mail) und den Buttons „Ich stimme zu“ / „Ich
  lehne ab“. Das Seitenskript „Gast-Seite füllen“ sucht die Veranstaltung zum
  Code; die Button-Skripte „Gast stimmt zu“ / „Gast lehnt ab“ speichern die
  Antwort mit der Herkunft „Gast“ und merken sich ihre Nummer in `session`.
  Lädt der Gast die Seite neu, sieht er seine Entscheidung; ein erneuter Klick
  ändert die Antwort, statt eine zweite anzulegen. Alles lässt sich im Designer
  ändern.
- Grenzen des Gast-Links: Niemand prüft, ob der Name stimmt; wer den Link hat,
  kann in fremdem Namen antworten. Ändern kann ein Gast seine Antwort nur im
  selben Browser; in einem anderen Browser oder nach dem Löschen der Cookies gilt
  er als neue Person, und es entsteht ein weiterer Eintrag. Der Gast-Link gilt, bis die
  Veranstaltung gelöscht oder die App nicht mehr veröffentlicht ist.
- Antworten entstehen nur über diese Seiten: In der Tabelle „Antworten“ sind
  Anlegen, Bearbeiten und Löschen abgeschaltet.
- Startseite und „Antworten“ zeigen, wie viele zugestimmt und abgelehnt haben,
  je Veranstaltung und als Liste mit CSV-Export.

**Wichtig vor echtem Einsatz:** Rechte gelten im Baukasten je App. Wer die
Teilnahme-Seite öffnen darf, kann auch die Seiten „Veranstaltungen“ und
„Antworten“ öffnen und sieht damit, wer abgelehnt hat. Für echte Einwilligungen
also die App auf die Organisatoren beschränken oder warten, bis es Rechte je
Seite gibt (siehe [Grenzen](#grenzen-des-jetzigen-stands)). Ist die App auf die
Organisatoren beschränkt, funktioniert der Gast-Link trotzdem: Öffentliche
Seiten brauchen keine Rechte an der App, nur dass sie veröffentlicht ist.

## Schnellstart: deine erste App in 15 Minuten

Als Beispiel baust du eine App für Urlaubsanträge. Du brauchst das Recht
„Designer“ (siehe [Rechte](#rechte)).

**1. App anlegen (1 Minute).** Oben rechts „Designer“ öffnen. Unter „Neue App“
den Namen *Urlaub* und ein Symbol, etwa 🌴, eintragen, „Anlegen“. Du landest in
der Übersicht der App mit drei nummerierten Kästen.

**2. Daten festlegen (5 Minuten).** Im Kasten „1 Daten: Tabellen“ die Tabelle
*Anträge* anlegen. Sie bekommt automatisch das Feld „Bezeichnung“. Füge rechts
unter „Feld hinzufügen“ diese Felder hinzu:

| Bezeichnung | Typ | Pflichtfeld |
|---|---|---|
| Von | Datum | ja |
| Bis | Datum | ja |
| Tage | Ganze Zahl | ja |
| Status | Auswahl, Werte: *offen*, *genehmigt*, *abgelehnt* (je eine Zeile) | ja |

**3. Seite erzeugen (1 Minute).** Oben „Seite aus dieser Tabelle erzeugen“
klicken. Die Seite „Anträge“ hat jetzt eine Liste mit Suche, „Neu“,
„Bearbeiten“ und „Löschen“. Mit „App öffnen“ siehst du sie so, wie Nutzer sie
sehen. Lege zwei, drei Anträge zum Ausprobieren an.

**4. Startseite gestalten (5 Minuten).** Zurück im Designer die Seite „Start“
öffnen. Im Seiten-Designer:

- den Text-Baustein entfernen (anklicken, rechts „Entfernen“),
- zwei *Kennzahlen* daneben setzen, Breite je „½“: „Anträge gesamt“
  (Anzahl) und „Beantragte Tage“ (Summe über das Feld *Tage*),
- ein *Kreisdiagramm* „Nach Status“, gruppiert nach *Status*,
- „Speichern“.

**5. Freigeben (1 Minute).** In der App unter „3 Einstellungen und Freigabe“
den Haken „Veröffentlicht“ setzen. Ohne Auswahl bei „Gruppen“ sehen jetzt alle
angemeldeten Personen die App; mit Auswahl nur die Mitglieder dieser Gruppen.

**6. Stand sichern (30 Sekunden).** Unter „Versionen“ eine Version mit der Notiz
*erste Fassung* speichern. Wenn ein späterer Umbau misslingt, holst du diesen
Stand mit „Wiederherstellen“ zurück.

Das war's. Nächste Schritte, wenn du willst: ein [Skript](#skripte), das den
Status nach dem Speichern prüft, oder die [API](#api-freischalten), damit Excel
oder ein anderes Programm die Anträge lesen kann.

---

## 1. Apps benutzen

### Anmelden

Öffne die Adresse des Baukastens. Je nach Einrichtung meldest du dich mit dem
Firmenkonto an („Mit Firmenkonto anmelden“, läuft über Keycloak) oder mit einem
lokalen Benutzernamen und Passwort.

### Startseite

Nach der Anmeldung siehst du deine Apps als Kacheln. Du siehst nur Apps, die
veröffentlicht und für dich freigegeben sind. Ein Klick öffnet die App; über
das Logo oben links kommst du jederzeit zurück.

### In einer App arbeiten

Oben stehen die Seiten der App. Was eine Seite zeigt, hat die Person festgelegt,
die die App gebaut hat. Typisch sind:

- **Listen:** Einträge mit Suchfeld. „Neu“ legt einen Eintrag an, „Bearbeiten“
  und „Löschen“ stehen am Ende jeder Zeile, sofern erlaubt.
- **Formulare:** neue Einträge direkt auf der Seite erfassen. Pflichtfelder
  werden beim Speichern geprüft.
- **Auswertungen:** Kennzahlen, Diagramme und Verläufe. Sie rechnen immer mit
  den aktuellen Daten.
- **CSV-Export:** lädt alle Einträge einer Tabelle für Excel herunter.

### Sprache

Die Oberfläche gibt es auf Deutsch und Englisch. Mit „DE | EN“ oben rechts
wechselst du; die Wahl wird gemerkt. Ohne eigene Wahl gilt die Sprache deines
Browsers. Übersetzt ist die Oberfläche des Baukastens. Inhalte, die jemand in
einer App eingetragen hat (Seitentitel, Feldnamen, Daten), bleiben so, wie sie
eingegeben wurden.

### Hell und Dunkel

Das Symbol neben „DE | EN“ schaltet das Erscheinungsbild um: Automatisch (halber
Kreis, folgt der Einstellung des Betriebssystems), Hell (Sonne), Dunkel (Mond).
Dasselbe geht im Profil unter „Einstellungen“. Die Wahl merkt sich der Browser;
sie gilt auf allen Seiten, auch in der Verwaltung unter `/admin/` und in der
API-Dokumentation.

### Seitenwechsel

Beim Wechsel zwischen Seiten blendet der Baukasten sanft über: Die Kopfzeile
bleibt stehen, die Markierung unter dem aktiven Reiter wandert mit, und der
Inhalt gleitet in Leserichtung herein (nach rechts weiter, nach links zurück).
Das funktioniert in Chrome, Edge und Safari; andere Browser wechseln ohne
Animation. Wer in den Einstellungen des Betriebssystems „Bewegung reduzieren“
eingeschaltet hat, bekommt keine Animation.

### Führung

Beim ersten Besuch startet auf wichtigen Seiten eine kurze Führung. Das
Fragezeichen oben rechts startet sie erneut. Mit Esc beendest du sie.

### Mein Profil

Ein Klick auf deinen Namen oben rechts öffnet dein Profil. Dort steht alles, was
zu dir gehört:

- **Rechte:** wie viele Apps du benutzen darfst, ob du Designer bist, ob du die
  Verwaltung (`/admin/`) öffnen darfst, und deine Gruppen. Gruppen, die jede
  Person automatisch hat, sind mit „Standard“ markiert.
- **Meine Apps:** alle Apps, die du öffnen darfst, und die, die du selbst
  angelegt hast.
- **Meine API-Schlüssel:** jeder Schlüssel, den du erzeugt hast, mit App,
  Rechten und letzter Nutzung. Eigene Schlüssel lassen sich hier löschen.
- **Meine Skripte:** mit dem Ergebnis des letzten Laufs und den letzten
  Fehlern, damit du Probleme früh siehst.
- **Meine Abfragen und Bausteine.**
- **Einstellungen:** Sprache, Erscheinungsbild (Hell, Dunkel, System),
  Führungen wieder anzeigen und, bei einem lokalen Konto, das Passwort ändern.

---

## 2. Apps bauen

Den Designer sieht, wer das Recht dazu hat (siehe [Rechte](#rechte)). Der Link
„Designer“ steht oben rechts.

### In drei Schritten zur App

1. **App anlegen:** Im Designer Name und Symbol eintragen, „Anlegen“.
2. **Daten festlegen:** Eine Tabelle anlegen (zum Beispiel „Geräte“) und ihr
   Felder geben.
3. **Seite erzeugen:** In der Tabelle auf „Seite aus dieser Tabelle erzeugen“
   klicken. Damit gibt es sofort eine Liste mit Suche, Anlegen, Bearbeiten und
   Löschen.

Danach passt du Seiten im Seiten-Designer an und veröffentlichst die App.

### Tabellen und Felder

Eine Tabelle beschreibt eine Art von Einträgen. Jedes Feld ist eine Angabe pro
Eintrag. Das erste Feld dient als Name des Eintrags, etwa in Verweisen.

| Feldtyp | Eingabe | Hinweis |
|---|---|---|
| Text | einzeilig | bis 500 Zeichen |
| Langer Text | mehrzeilig | |
| Ganze Zahl | Zahl ohne Komma | für Summe und Durchschnitt nutzbar |
| Kommazahl | Zahl mit Komma | für Summe und Durchschnitt nutzbar |
| Datum | Datumsauswahl | für den Baustein „Verlauf“ nutzbar |
| Ja/Nein | Kästchen | |
| Auswahl | feste Werte | ein Wert pro Zeile unter „Auswahlwerte“ |
| E-Mail, Link | geprüfte Eingabe | |
| Verweis auf Tabelle | Eintrag einer anderen Tabelle | Zieltabelle unter „Verweist auf“ wählen |

Zu jedem Feld gehört ein technischer Kurzname (zum Beispiel `anschaffung`). Er
entsteht aus der Bezeichnung, bleibt danach fest und wird in der API und in
Python-Erweiterungen verwendet. Im Designer steht er grau neben der Bezeichnung.

Bei jedem Feld lässt sich außerdem festlegen, ob es **in Listen** und **im
Formular** erscheint. Felder, die ein Skript füllt (zum Beispiel ein erzeugter
Link), schaltest du im Formular ab; ihr Wert bleibt beim Bearbeiten erhalten.
Felder vom Typ „Link“ sind in Listen anklickbar.

Pro Tabelle lässt sich abschalten, ob Einträge angelegt, bearbeitet oder
gelöscht werden dürfen. Das gilt für die Oberfläche und für die API.

**Wichtig:** Wird ein Feld gelöscht, verschwindet es aus Listen und Formularen;
die bereits erfassten Werte bleiben gespeichert. Wird eine Tabelle gelöscht,
sind ihre Einträge endgültig weg.

### Seiten-Designer

Links wählst du Bausteine, in der Mitte ordnest du sie an, rechts stellst du
den gewählten Baustein ein.

- **Hinzufügen:** Baustein auf die Seite ziehen oder anklicken.
- **Verschieben:** Baustein auf der Seite an eine andere Stelle ziehen, oder
  rechts „Nach vorn“ / „Nach hinten“.
- **Breite:** Eine Seite hat zwölf Spalten. Bausteine belegen ein Viertel, ein
  Drittel, die Hälfte, zwei Drittel oder die ganze Breite. Auf schmalen
  Bildschirmen stehen alle untereinander.
- **Vorschau:** Die Arbeitsfläche zeigt jeden Baustein mit echten Daten, noch
  bevor gespeichert ist.
- **Speichern:** Änderungen gelten erst nach „Speichern“. „Vorschau“ öffnet die
  Seite so, wie Nutzer sie sehen.

### Öffentliche Seiten

Oben im Seiten-Designer macht der Haken **„Ohne Anmeldung erreichbar“** eine
Seite öffentlich: Jeder mit dem Link kann sie öffnen, auch ohne Konto und ohne
Rechte an der App. Damit baust du Anmeldeformulare, Umfragen oder Einwilligungen
für Externe. In der Seitenliste der App steht dann „öffentlich“.

Was Gäste dürfen und was nicht:

- **Nur diese Seite.** Alle anderen Seiten der App führen zur Anmeldung; das
  Menü zeigt Gästen nur öffentliche Seiten.
- **Formulare** auf der Seite dürfen sie absenden: Der Eintrag landet in der
  Tabelle des Formulars (wenn „Anlegen erlaubt“ an ist). Bearbeiten, Löschen
  und CSV-Export bleiben angemeldeten Personen vorbehalten.
- **Skript-Buttons** auf der Seite dürfen sie auslösen. Skripte bekommen für
  Gäste `user = None`; prüfe Eingaben im Skript selbst. JavaScript-Skripte
  funktionieren für Gäste nicht.
- **Achtung bei Daten:** Listen, Karten, Kennzahlen, Diagramme und Abfragen auf
  einer öffentlichen Seite zeigen ihre Daten allen. Der Designer warnt, sobald
  der Haken gesetzt ist.
- Die App muss veröffentlicht sein. Je Adresse sind höchstens 120 Anfragen pro
  Minute möglich (`PUBLIC_RATE`).

**Eingaben für Skripte.** Der Baustein **Eingabefeld** (Gruppe „Skripte“) hat
einen Namen, z. B. `vorname`. Klickt jemand einen Skript-Button derselben Seite,
gehen alle Eingabefelder mit; das Skript liest sie als `params["vorname"]`.
Pflichtfelder prüft schon der Browser. Werte aus der Adresse (`?vorname=Ada`)
füllen das Feld vor.

**Wiedererkennen ohne Konto.** Skripte haben `session`, einen Merkzettel je
Besucher und App, der über Seitenaufrufe erhalten bleibt (Sitzungs-Cookie, auch
für Gäste). Ein Button-Skript merkt sich z. B. `session["antwort"] = neu["id"]`,
das Seitenskript zeigt dann beim Neuladen die gespeicherte Antwort und blendet
Eingaben aus. So entstehen keine doppelten Einträge durch zweimal Klicken. Der
Merkzettel gilt nur in diesem Browser.

**Geheime Links.** Für Seiten wie „Gast“ der Beispiel-App, die nur mit einem
bestimmten Link funktionieren sollen: Im Skript mit `token()` einen
Zufallscode erzeugen, im Eintrag speichern, als `?code=…` an den Link hängen
und auf der Seite mit `app.table("…").first(gast_code=params["code"])`
prüfen.

### Bausteine

| Gruppe | Baustein | Zweck |
|---|---|---|
| Inhalt | Überschrift | Titel in drei Größen, optional mit Unterzeile |
| | Text | Absatz mit Zeilenumbrüchen |
| | Hinweis | farbiger Kasten: Information, Erfolg, Warnung, Wichtig |
| | Bild | Bild von einer https-Adresse oder aus `/static/` |
| | Begrüßung | „Hallo <Name>“ mit Datum |
| Daten | Liste | Tabelle mit Suche, Blättern, Anlegen, Bearbeiten, Löschen |
| | Karten | dieselben Einträge als Karten |
| | Formular | neuen Eintrag direkt auf der Seite erfassen |
| | CSV-Export | alle Einträge einer Tabelle herunterladen |
| Auswertung | Kennzahl | Anzahl, Summe oder Durchschnitt, optional mit Einheit |
| | Fortschritt | Wert im Verhältnis zu einem Zielwert |
| | Balkendiagramm | Einträge je Wert eines Feldes, als Rangliste |
| | Kreisdiagramm | Anteile der fünf häufigsten Werte, Rest als „Sonstige“ |
| | Verlauf | Einträge pro Monat, nach einem Datumsfeld oder dem Erfassungsdatum |
| Navigation | Button | öffnet eine Seite, einen Link oder führt eine Python-Aktion aus |
| | Seitenkacheln | Kacheln zu allen Seiten der App |
| Layout | Trennlinie, Abstand | gliedern die Seite |
| Anbindung | Web-Request | ruft JSON von einer freigegebenen Adresse ab und zeigt es |
| Skripte | Ausgabe | zeigt Werte, Text oder Tabellen, die ein Skript setzt |
| | Eingabefeld | Text, E-Mail, Zahl oder langer Text, den ein Skript-Button mitschickt (`params["…"]`) |
| Eigene Bausteine | siehe unten | |

### Eigene Bausteine

Wenn die mitgelieferten Bausteine nicht reichen, gibt es zwei Wege ohne
Programmierung. Beide findest du unter **Designer → Eigene Bausteine**; die
Ergebnisse stehen im Seiten-Designer aller Apps.

**Vorlagen** sind fertig eingestellte Standard-Bausteine. Stelle im
Seiten-Designer einen Baustein ein, trage rechts unter „Wiederverwenden“ einen
Namen ein und klicke „Als Vorlage speichern“. Die Vorlage erscheint links unter
„Vorlagen“. Beim Einfügen entsteht eine unabhängige Kopie: Spätere Änderungen
an einer Seite ändern die Vorlage nicht, und umgekehrt.

**HTML-Bausteine** bestehen aus eigenem HTML und aus Einstellungen, die du
selbst festlegst:

- *Einstellungen:* eine pro Zeile im Format `Bezeichnung = Standardwert`. Jede
  Zeile wird im Seiten-Designer zu einem Eingabefeld.
- *HTML:* Wo `{{ bezeichnung }}` steht, erscheint später der eingestellte Wert.
  Der Platzhalter ist die Bezeichnung in Kleinbuchstaben, Leerzeichen werden
  zu Unterstrichen (`Ansprech Partner` → `{{ ansprech_partner }}`).
- *Immer verfügbar:* `{{ nutzer }}` (angemeldete Person), `{{ app }}` (Name
  der App), `{{ datum }}` (heutiges Datum).

Beispiel:

```
Einstellungen:
  Titel = Wartung
  Text = Am Freitag ist das System ab 16 Uhr nicht erreichbar.

HTML:
  <div class="card">
    <h3>{{ titel }}</h3>
    <p>{{ text }}</p>
  </div>
```

Aus Sicherheitsgründen wird das HTML beim Speichern und bei jeder Anzeige
bereinigt. Erlaubt sind übliche Tags (`div`, `span`, `p`, `h1`–`h4`, `strong`,
`em`, `ul`, `ol`, `li`, `a`, `img`, `table` und verwandte) mit den Attributen
`class`, `title`, `style`, bei Links `href`, bei Bildern `src` und `alt`.
Entfernt werden Skripte, Ereignis-Attribute wie `onclick`, eingebettete
Fremdinhalte (`iframe`) sowie Adressen, die nicht mit `https://`, `/`,
`mailto:` oder `#` beginnen. Eingetragene Werte werden immer als Text
eingesetzt, nie als HTML.

Die Klassen der Oberfläche kannst du mitverwenden, zum Beispiel `card`, `btn`,
`btn-secondary`, `muted`, `small`, `badge`, `notice`.

Wer mehr braucht (Daten abfragen, rechnen), schreibt einen Baustein in Python,
siehe [Erweiterungen](#erweiterungen-in-python).

### Veröffentlichen und freigeben

In den Einstellungen der App:

- **Veröffentlicht:** Erst mit Haken sehen Nutzer die App. Vorher ist sie ein
  Entwurf und nur für Designer sichtbar.
- **Gruppen:** Ohne Auswahl dürfen alle angemeldeten Nutzer die App verwenden.
  Mit Auswahl nur Mitglieder dieser Gruppen. Mit Keycloak kommen die Gruppen
  von dort.

### Übersetzungen

Eine App baust du in einer Sprache, der Quellsprache (Deutsch). Für jede weitere
Sprache der Oberfläche (zurzeit Englisch) trägst du Übersetzungen ein; wer oben
auf **EN** umschaltet, sieht dann auch die App auf Englisch.

1. Im Designer der App, Abschnitt „Übersetzungen“, auf **Übersetzungen
   bearbeiten** klicken.
2. Die Seite listet automatisch alle Texte der App: App-Name und Beschreibung,
   Tabellen, Feldnamen, Auswahlwerte, Seitentitel und die Texte der Bausteine
   (Überschriften, Hinweise, Beschriftungen, Buttons). Daneben steht, wo der Text
   vorkommt.
3. Übersetzung eintragen, speichern. Leere Felder zeigen den Originaltext.
   „Nur fehlende Übersetzungen zeigen“ blendet Erledigtes aus.

Gut zu wissen:

- **Gleicher Text, gleiche Übersetzung.** Kommt „Status“ an drei Stellen vor,
  genügt eine Übersetzung.
- **Text geändert, Übersetzung weg.** Ändert jemand den Originaltext, fehlt die
  Übersetzung, bis sie neu eingetragen ist.
- **Daten bleiben, wie sie sind.** Ein Auswahlwert „Zustimmung“ steht so in der
  Datenbank, in der API, im CSV-Export und in Skripten; nur die Anzeige und das
  Formular zeigen „Consent“. Filter und Skripte funktionieren in jeder Sprache
  gleich.
- **Nicht übersetzt** werden erfasste Daten (z. B. der Titel einer
  Veranstaltung), Texte, die Skripte setzen (`ui.set`, `message`), eigene
  HTML-Bausteine und der Designer selbst. In Python-Skripten hilft
  `app.t("Text")`; `user["language"]` sagt, welche Sprache die Person gewählt
  hat.
- **Für Übersetzer ohne Designer-Zugang:** „Als CSV herunterladen“, in Excel die
  Spalte `en` ausfüllen, unter „CSV einlesen“ wieder hochladen. Übernommen
  werden nur ausgefüllte Zellen zu Texten, die es in der App gibt.
- Übersetzungen gehören zu Versionen und zum App-Export.

### Versionen

Eine Version hält den **Aufbau** einer App fest: Einstellungen, Tabellen, Felder,
Seiten und Übersetzungen. Die erfassten Daten gehören nicht dazu.

- **Speichern:** In der App unter „Versionen“ optional eine Notiz eintragen und
  „Version speichern“ klicken. Versionen werden fortlaufend nummeriert.
- **Wiederherstellen:** bringt Einstellungen, Felder und Seiten auf den
  gespeicherten Stand. Vorher wird der aktuelle Stand automatisch als neue
  Version gesichert, das Zurückgehen lässt sich also selbst zurücknehmen.
- **Daten bleiben erhalten:** Einträge werden nie gelöscht. Tabellen, die es in
  der alten Version noch nicht gab, bleiben mitsamt ihren Daten bestehen; der
  Baukasten weist darauf hin. Felder, die es damals nicht gab, verschwinden aus
  der Oberfläche, ihre Werte bleiben gespeichert.
- **Herunterladen und importieren:** „Herunterladen“ liefert die Version als
  Datei. Auf der Startseite des Designers legt „App aus Datei anlegen“ daraus
  eine neue App an, zum Beispiel um eine App von der Test- in die
  Produktivumgebung zu bringen. Die neue App ist zunächst ein Entwurf.

Versionen entstehen nicht automatisch bei jeder Änderung. Speichere eine, bevor
du größere Umbauten beginnst.

### App löschen

Eine App löschst du in der App-Liste des Designers („Löschen“) oder in der App
ganz unten („App löschen“). Gelöscht werden Tabellen, Daten, Seiten, Versionen
und API-Schlüssel. Das lässt sich nicht rückgängig machen. Lade vorher eine
Version herunter, wenn du den Aufbau behalten willst.

### API freischalten

Unter „Schnittstelle (API)“ in der App:

1. Tabellen anhaken, die erreichbar sein sollen, und „Freigaben speichern“.
2. Einen Schlüssel erzeugen. Er wird **nur einmal** angezeigt; kopiere ihn
   sofort. Ohne Haken bei „Darf schreiben“ kann der Schlüssel nur lesen.
3. Den Schlüssel an das Programm oder die Person geben, die ihn braucht.

**API-Dokumentation.** „API-Dokumentation öffnen“ (in der App unter
„Schnittstelle (API)“, im Profil oder unter `/api-doku/`) zeigt für jede App
eine Seite mit allen Adressen, allen Feldern samt Typ und einer Swagger-
Oberfläche, in der sich jede Anfrage direkt ausprobieren lässt: „Authorize“
anklicken, Schlüssel eintragen, bei einer Anfrage „Try it out“ und „Execute“.
**Vorsicht:** Ausprobierte Anfragen wirken auf echte Daten. Die Dokumentation
entsteht automatisch aus den Tabellen und ist daher immer aktuell.

Wie die API im Einzelnen funktioniert, steht in [Teil 3](#api).

### Daten aus Datenbanken und Databricks

Apps können Daten aus bestehenden Datenbanken anzeigen, etwa aus PostgreSQL,
SQL Server, MySQL oder einem Databricks SQL-Warehouse. Welche **Datenquellen**
es gibt, legt der Betrieb fest (siehe [Datenquellen einrichten](#datenquellen-einrichten));
im Designer siehst du sie bei jeder Abfrage unter „Eingerichtete Datenquellen“.
Zugangsdaten bekommst du dabei nie zu sehen.

**Abfrage anlegen.** In der App unter „Datenquellen“ eine neue Abfrage
anlegen: Name, Datenquelle und SQL. Erlaubt ist eine einzelne lesende Abfrage,
die mit `SELECT` oder `WITH` beginnt. „Speichern und testen“ zeigt die ersten
Zeilen des Ergebnisses.

```sql
SELECT linie, SUM(stueck) AS stueck, MAX(zeitpunkt) AS letzte_meldung
FROM werk.ausstoss
WHERE tag = current_date()
GROUP BY linie
```

Werte, die sich ändern sollen, gehören nicht direkt ins SQL, sondern werden als
Parameter `:name` geschrieben und von einem Skript übergeben (siehe unten).

Es gibt zwei Arten, die Daten zu nutzen:

| | Live anzeigen | In eine Tabelle spiegeln |
|---|---|---|
| Wie | Baustein „Datenbank-Abfrage“ | Abfrage mit „In Tabelle spiegeln“ |
| Aktualität | bei jedem Seitenaufruf, optional alle 10 s bis 5 min automatisch | im eingestellten Intervall, frühestens jede Minute, oder per Knopfdruck |
| Last auf der Datenbank | höchstens eine Abfrage je Zwischenspeicher-Zeit, egal wie viele zuschauen | eine Abfrage pro Abgleich |
| Weiterverwenden | nur anzeigen; in Skripten mit `db.saved(…)` | wie jede Tabelle: Listen, Diagramme, Kennzahlen, Suche, CSV-Export, API, Skripte |
| Gut für | aktuelle Stände, kleine Ergebnisse (bis 2.000 Zeilen) | Auswertungen, größere Datenmengen (bis 50.000 Zeilen) |

**Live anzeigen.** Im Seiten-Designer den Baustein „Datenbank-Abfrage“ einfügen
und die Abfrage wählen. Unter „Automatisch aktualisieren“ (gilt für jeden
Baustein) lädt sich der Baustein im Browser regelmäßig neu, ohne dass die Seite
neu lädt. „Ergebnis zwischenspeichern“ an der Abfrage legt fest, wie lange ein
Ergebnis wiederverwendet wird; so fragen 50 offene Browser die Datenbank nicht
50-mal ab.

Damit eine langsame Datenquelle die App nicht ausbremst, gilt außerdem:

- Die Seite erscheint sofort. Der Baustein zeigt kurz „Daten werden geladen …“
  und füllt sich, sobald das Ergebnis da ist.
- Fragen viele Personen gleichzeitig dieselbe Abfrage an, geht sie trotzdem nur
  einmal an die Datenquelle; alle bekommen dasselbe Ergebnis.
- Ist die Datenquelle ausgelastet, wartet der Baustein und versucht es
  selbstständig erneut.
- Antwortet die Datenquelle nicht, zeigt der Baustein den letzten Stand mit
  einem gelben Hinweis, statt leer zu bleiben.
- Live-Abfragen dürfen höchstens 25 Sekunden dauern (einstellbar durch den
  Betrieb). Was länger braucht, gehört gespiegelt.

**In eine Tabelle spiegeln.** Bei der Abfrage „In Tabelle spiegeln“ wählen
(oder leer lassen: beim ersten Abgleich entsteht eine neue Tabelle mit dem Namen
der Abfrage) und ein Intervall eintragen. Die Felder entstehen aus den Spalten
der Abfrage. Mit einer **Schlüsselspalte** (zum Beispiel `id`) werden geänderte
Zeilen aktualisiert, neue ergänzt und verschwundene entfernt; Einträge behalten
dabei ihre Nummer. Ohne Schlüsselspalte wird die Tabelle bei jedem Abgleich neu
befüllt. Gespiegelte Tabellen sind zum Lesen da: Anlegen, Bearbeiten und Löschen
sind abgeschaltet, denn der nächste Abgleich würde Änderungen überschreiben.

**Databricks.** Ein SQL-Warehouse, das gerade schläft, braucht zum Starten oft
einige Minuten. Für Live-Anzeigen eignet sich daher ein Warehouse, das läuft;
sonst ist Spiegeln die bessere Wahl: Der Abgleich im Hintergrund darf bis zu
5 Minuten warten.

**Faustregel:** Alles, was minutenaktuell sein darf, spiegeln. Live nur für
kleine Ergebnisse, die wirklich sekundenaktuell sein müssen, und dann mit
„Ergebnis zwischenspeichern“ von mindestens 30 Sekunden. Tabellen sprichst du mit `katalog.schema.tabelle`
an, oder der Betrieb legt Katalog und Schema in der Datenquelle fest.

### Skripte

Mit Skripten rechnest du Werte aus, füllst Bausteine, prüfst oder ergänzt
Einträge und erledigst Aufgaben im Hintergrund. Es gibt sie in **Python** (läuft
auf dem Server) und **JavaScript** (läuft im Browser). Angelegt werden sie in der
App unter „Skripte“; ein Testlauf zeigt Ausgabe, Fehler mit Zeilennummer und
welche Bausteine gefüllt wurden. **Testläufe arbeiten mit echten Daten.**

| Auslöser | Python | JavaScript |
|---|---|---|
| Beim Öffnen einer Seite (eine bestimmte oder alle) | ✓ vor der Anzeige | ✓ nach dem Laden |
| Per Button (Button-Baustein, „Skript ausführen“) | ✓ | ✓ ohne Neuladen der Seite |
| Nach dem Speichern eines Eintrags | ✓ | – |
| Zeitgesteuert im Hintergrund | ✓ | – |

Faustregel: **Python**, wenn es um Daten, Abfragen mit Parametern, andere
Systeme oder Hintergrundarbeit geht. **JavaScript**, wenn etwas auf Knopfdruck
sofort auf der Seite passieren soll.

**Bausteine füllen.** Gib dem Baustein im Seiten-Designer unter „Name für
Skripte“ einen Namen, etwa `ergebnis`. Ein Skript setzt dann dessen Inhalt:

```python
offen = app.table("antraege").count(status="offen")
ui.set("ergebnis", value=offen, unit="offen")
```

| Wert | Wirkt bei |
|---|---|
| `value`, `unit`, `label` | Ausgabe, Kennzahl |
| `rows` (Liste von Dictionaries) | Ausgabe: wird als Tabelle gezeigt |
| `text`, `title`, `subtitle` | Überschrift, Text, Hinweis, Ausgabe |
| `tone` (`info`, `success`, `warning`, `danger`) | Hinweis |
| `label` | Button |
| `values` (`{"feld": wert}`) | Formular: Felder vorbelegen |
| `ui.hide("name")` | jeder Baustein: ausblenden |

Für reine Skript-Ergebnisse gibt es den Baustein **Ausgabe** (Gruppe „Skripte“).
Er zeigt einen Wert, einen Text oder eine Tabelle, je nachdem, was das Skript
setzt.

**Nach dem Speichern** bekommt das Skript den Eintrag als `record` und darf ihn
ändern; die Änderung wird übernommen:

```python
if not record.get("standort"):
    record["standort"] = "Lager"
```

Das gilt für Eingaben über Formulare und über die API. Was ein Skript selbst
speichert, löst keine weiteren Skripte aus, damit keine Schleifen entstehen.

**Zeitgesteuert** laufen Skripte im eingestellten Intervall, etwa um nachts
Daten zu verdichten oder einen Wert von einem anderen System abzuholen. Dafür
muss der [Hintergrunddienst](#hintergrundarbeiten) laufen.

Alle Befehle stehen in der Kurzreferenz neben dem Code-Feld und in
[Teil 3](#skripte-referenz).

---

## 3. Entwickeln

### Lokal starten

Voraussetzung: Python 3.10 oder neuer.

```
python -m venv .venv
.venv\Scripts\activate            (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

$env:DEBUG=1                      (cmd: set DEBUG=1, Linux/macOS: export DEBUG=1)
python manage.py migrate
python manage.py createsuperuser
python manage.py demo             (Beispiel-App „Inventar“; mit --neu wird sie ersetzt)
python manage.py runserver
```

Zeitgesteuerte Skripte und das Spiegeln von Abfragen erledigt ein eigener
Befehl. Beim Entwickeln in einem zweiten Terminal starten:

```
python manage.py hintergrund --dauerhaft
```

Mit `DEBUG=1` legt `python manage.py demo` zusätzlich eine kleine
Beispiel-Datenquelle `demo` an (Datei `demo-datenquelle.sqlite3`) und die Seite
„Live-Daten“ mit einem Python- und einem JavaScript-Skript.

Tests: `python manage.py test` (mit `DEBUG=1`).

### Aufbau des Codes

```
config/              Einstellungen, URLs
builder/
  models.py          App, Entity (Tabelle), Field, Record (Eintrag), Page,
                     CustomBlock, ApiKey, AppVersion
  blocks.py          Bausteine: Schema, Datenabfrage, Prüfung des Layouts
  forms.py           Formulare; RecordForm entsteht aus den Feldern einer Tabelle
  views.py           Laufzeit: Startseite, Seiten, Einträge, CSV-Export
  designer.py        Designer: Apps, Tabellen, Felder, Seiten, Bausteine, Versionen
  api.py             JSON-API
  versions.py        Versionen: Stand erzeugen, anwenden, importieren
  sanitize.py        Bereinigung des HTML eigener Bausteine
  hooks.py           Erweiterungspunkte für Python
  services.py        Web-Requests mit Host-Freigabe
  datasources.py     externe Datenbanken: Verbindungen, Prüfung, Abfragen, Spiegeln
  scripting/         Skripte: python.py startet den abgeschotteten Prozess,
                     child.py läuft darin, ops.py beantwortet Tabellen-Anfragen,
                     triggers.py legt fest, wann Skripte laufen
  auth.py            Anmeldung über Keycloak
  tours.py           Texte der Führungen
  locale/en/         englische Übersetzung
  static/builder/    theme.css, theme.js, style.css, designer.js, tour.js, transitions.js, Schrift, Logo
  templates/         Vorlagen
  tests.py           automatische Tests
extensions/          eigene Python-Erweiterungen
clients/python/      Python-Bibliothek baukasten-client für die API
docs/                dieses Handbuch
k8s/                 Kubernetes-Manifeste (app, migrate-job, cronjob, optional redis)
gunicorn.conf.py     Prozesse, Threads und Zeitlimits des Webservers
```

Zwei Entwurfsentscheidungen sollte man kennen:

- **Einträge liegen als JSON** in einer gemeinsamen Tabelle (`Record.data`).
  Dadurch braucht eine im Designer geänderte Tabelle keine Datenbank-Migration.
  Für sehr große Datenmengen oder komplexe Abfragen ist ein normales
  Django-Modell die bessere Wahl.
- **Eine Seite ist eine Liste von Bausteinen** (`Page.layout`), jeder mit
  `id`, `type`, `width` und `props`. `blocks.clean_layout` übernimmt aus dem
  Designer nur bekannte Bausteine und bekannte Einstellungen.

### Erweiterungen in Python

Jede Python-Datei im Ordner `extensions/` wird beim Start geladen. Beispiele
stehen in `extensions/beispiel.py`. Nach einer Änderung muss die Anwendung neu
starten (in Kubernetes: neues Image ausrollen).

```python
from builder import hooks
from builder.services import http_json
```

| Dekorator | Wirkung | Signatur der Funktion |
|---|---|---|
| `@hooks.action("name", label="…")` | Aktion, die ein Button auslöst | `(request, app)` → Meldungstext oder `HttpResponse` |
| `@hooks.on_save(entity="…", app="…")` | läuft nach jedem Speichern eines Eintrags | `(record, created, user)` |
| `@hooks.block("name", label="…")` | eigener Baustein im Seiten-Designer | `(request, app)` → Text oder `format_html(...)` |
| `@hooks.api("name", methods=("GET",), write=False)` | eigener API-Endpunkt | `(request, app, daten)` → Dictionary oder Liste |

`entity` und `app` bei `on_save` sind die Kurznamen aus der Adresse (zum
Beispiel `gerate` für „Geräte“) und schränken den Hook ein; ohne Angabe gilt er
für alles. Fehler in einem Hook werden protokolliert und brechen das Speichern
nicht ab.

Einträge liest und schreibt man über das Modell:

```python
from builder.models import Record

@hooks.action("inventur", label="Inventur abschließen")
def inventur(request, app):
    geraete = Record.objects.filter(entity__app=app, entity__slug="gerate")
    aktiv = geraete.filter(data__aktiv=True).count()
    return f"{aktiv} aktive Geräte gezählt."
```

**Web-Requests** an andere Systeme laufen über `http_json(url)` oder
`http_request(method, url, …)` aus `builder.services`. Aufrufe gehen nur an
Hosts, die in der Einstellung `HTTP_ALLOWED_HOSTS` stehen; alles andere wird
abgelehnt. Das gilt auch für den Baustein „Web-Request“.

### API

Jede App hat eine JSON-API für die Tabellen, die im Designer freigeschaltet
sind. Die vollständige, immer aktuelle Beschreibung jeder App steht in der
Oberfläche unter `/a/<app>/api-doku/` (Swagger). Für Werkzeuge wie Postman,
Insomnia oder Code-Generatoren gibt es sie als OpenAPI-Datei unter
`/api/v1/<app>/openapi.json`, abrufbar mit einem Schlüssel der App.

Jede Anfrage braucht einen Schlüssel der App:

```
Authorization: Bearer bk_…
```

| Methode | Adresse | Wirkung |
|---|---|---|
| GET | `/api/v1/<app>/` | beschreibt Tabellen, Felder und eigene Endpunkte |
| GET | `/api/v1/<app>/<tabelle>/` | Liste der Einträge |
| POST | `/api/v1/<app>/<tabelle>/` | Eintrag anlegen |
| GET | `/api/v1/<app>/<tabelle>/<id>/` | Eintrag lesen |
| PUT | `/api/v1/<app>/<tabelle>/<id>/` | Eintrag vollständig ersetzen |
| PATCH | `/api/v1/<app>/<tabelle>/<id>/` | einzelne Felder ändern |
| DELETE | `/api/v1/<app>/<tabelle>/<id>/` | Eintrag löschen |
| je nach Endpunkt | `/api/v1/<app>/x/<name>/` | eigener Endpunkt aus `extensions` |

`<app>` und `<tabelle>` sind die Kurznamen, die im Designer grau angezeigt
werden.

**Liste abfragen.** Parameter: `page`, `page_size` (höchstens 200, Standard 50),
`q` (Volltextsuche) und Filter nach Feldern mit ihrem Kurznamen:

```
curl -H "Authorization: Bearer $KEY" \
  "https://baukasten.example.com/api/v1/inventar/gerate/?kategorie=IT&page_size=20"
```

```json
{
  "count": 3, "page": 1, "pages": 1, "page_size": 20,
  "results": [
    {"id": 6, "bezeichnung": "Beamer", "kategorie": "IT", "standort": "Besprechung A",
     "anschaffung": "2026-02-10", "preis": 640.0, "aktiv": true,
     "created_at": "2026-11-16T16:27:05+00:00", "updated_at": "2026-11-16T16:27:05+00:00"}
  ]
}
```

Datumswerte sind Text im Format `JJJJ-MM-TT`, Verweise die Nummer (`id`) des
Zieleintrags.

**Eintrag anlegen.** Der Inhalt ist ein JSON-Objekt mit den Kurznamen der
Felder. Es gelten dieselben Prüfungen wie im Formular.

```
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"bezeichnung": "Kamera", "kategorie": "IT", "preis": 499.5}' \
  https://baukasten.example.com/api/v1/inventar/gerate/
```

**Antworten.**

| Status | Bedeutung |
|---|---|
| 200, 201, 204 | gelesen, angelegt, gelöscht |
| 400 | ungültige Daten; `fields` nennt die Fehler je Feld |
| 401 | Schlüssel fehlt, ist falsch oder gehört zu einer anderen App |
| 403 | Schlüssel darf nur lesen, oder die Tabelle erlaubt die Aktion nicht |
| 404 | Tabelle nicht freigeschaltet oder Eintrag nicht vorhanden |
| 405 | Methode nicht erlaubt |

Fehler haben die Form `{"error": "…"}`.

**Schlüssel.** Gespeichert wird nur ein Hash; der Klartext ist nach dem
Erzeugen nicht mehr auslesbar. Ein gelöschter Schlüssel funktioniert sofort
nicht mehr. Der Designer zeigt, wann ein Schlüssel zuletzt benutzt wurde.

### MCP-Server (KI-Agenten, n8n)

Jede App ist zusätzlich ein MCP-Server (Model Context Protocol) unter
`/mcp/<app>/`. Damit können KI-Agenten die Tabellen der App als Werkzeuge
nutzen: n8n („MCP Client Tool“ im AI Agent), Claude, Cursor und andere.

- **Transport:** „HTTP Streamable“ ohne Streaming. Jede Anfrage ist ein POST mit
  einer JSON-RPC-Nachricht. Server-Sent Events gibt es nicht.
- **Anmeldung:** derselbe Schlüssel wie für die API, im Kopf
  `Authorization: Bearer bk_…`.
- **Tools entstehen automatisch** aus den für die API freigeschalteten Tabellen,
  je Tabelle mit dem Kurznamen `<tabelle>`:

| Tool | Wirkung | nur mit Schreibrecht |
|---|---|---|
| `list_<tabelle>` | suchen: Volltext `q`, Filter je Feld, `page`, `page_size` | nein |
| `get_<tabelle>` | einen Eintrag lesen (`id`) | nein |
| `create_<tabelle>` | anlegen, mit denselben Prüfungen wie im Formular | ja, und Anlegen erlaubt |
| `update_<tabelle>` | einzelne Felder ändern (`id` + Felder) | ja, und Bearbeiten erlaubt |
| `delete_<tabelle>` | löschen (`id`) | ja, und Löschen erlaubt |
| `x_<name>` | eigener Endpunkt aus `extensions` | wenn der Endpunkt schreibt |

Beschreibungen und Eingabefelder der Tools kommen aus den Feldern der Tabelle
(Bezeichnung, Typ, Pflichtfeld, Auswahlwerte). Ändert jemand im Designer ein
Feld, sieht der Agent das beim nächsten Abruf. Für einen Agenten, der nur
lesen soll, einen Schlüssel ohne „Darf schreiben“ verwenden.

**In n8n einrichten:**

1. Im Designer der App Tabellen freischalten und einen Schlüssel erzeugen.
2. In n8n einen „AI Agent“ anlegen und als Tool „MCP Client Tool“ hinzufügen.
3. Endpoint: `https://baukasten.example.com/mcp/<app>/`.
   Läuft n8n lokal in Docker und der Baukasten in Docker Desktop:
   `http://host.docker.internal:8080/mcp/<app>/`.
4. Server Transport: „HTTP Streamable“.
5. Authentication: „Bearer Auth“ mit dem Schlüssel.
6. Tools to Include: „All“ oder einzelne Tools auswählen.

Zum Ausprobieren ohne n8n:

```
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  https://baukasten.example.com/mcp/inventar/
```

Der Host, unter dem n8n den Baukasten aufruft, muss in `ALLOWED_HOSTS` stehen.

**Eigener Endpunkt:**

```python
@hooks.api("statistik")                                  # GET /api/v1/<app>/x/statistik/
def statistik(request, app, daten):
    return {"tabellen": {e.name: e.records.count() for e in app.entities.all()}}

@hooks.api("buchen", methods=("POST",), write=True)      # braucht einen Schlüssel mit Schreibrecht
def buchen(request, app, daten):
    ...
    return {"ok": True}
```

`daten` ist bei POST, PUT und PATCH der JSON-Inhalt, bei GET die
Abfrageparameter.

### Skripte: Referenz

Python und JavaScript haben dieselben Befehle; in JavaScript gibt jeder Befehl,
der Daten holt, ein Promise zurück (`await` davor schreiben), und Felder werden
als Objekt übergeben.

| Python | JavaScript | Wirkung |
|---|---|---|
| `app.table("t").all()` | `await app.table("t").all()` | alle Einträge (höchstens 1.000) |
| `.filter(feld=wert)` | `.filter({feld: wert})` | Einträge mit gleichem Wert |
| `.first(feld=wert)` / `.get(id)` | dito | ein Eintrag oder `None`/`null` |
| `.count(feld=wert)` | dito | Anzahl |
| `.sum("feld")` / `.avg("feld")` | dito | Summe / Durchschnitt eines Zahlenfelds |
| `.create(feld=wert)` | `.create({feld: wert})` | anlegen, mit denselben Prüfungen wie im Formular |
| `.update(id, feld=wert)` | `.update(id, {feld: wert})` | einzelne Felder ändern |
| `.delete(id)` | dito | löschen |
| `db.saved("abfrage")` | `await db.saved("abfrage")` | Ergebnis einer gespeicherten Abfrage (Liste von Zeilen) |
| `db.query("quelle", sql, {"x": 1})` | – | freie lesende Abfrage mit Parametern `:x` |
| `http.get_json(url)` / `http.post_json(url, daten)` | – | anderes System aufrufen (nur freigegebene Hosts) |
| `ui.set("name", …)` / `ui.hide("name")` | `ui.set("name", {…})` / `ui.hide("name")` | Baustein füllen bzw. ausblenden |
| `message("Text")` | `message("Text")` | Meldung für die Person, die das Skript ausgelöst hat |
| `token()` / `token(32)` | – | zufälliger, nicht erratbarer Code, z. B. für geheime Links |
| `session["schlüssel"]` | – | Merkzettel je Besucher (Browser) und App, bleibt über Seitenaufrufe erhalten; auch für Gäste ohne Konto. Höchstens 4 KB, nur einfache Werte (Text, Zahlen, Listen, Dictionaries) |
| `print(…)` | `console.log(…)` | Ausgabe im Protokoll bzw. Testlauf |
| `app.name`, `app.slug` | – | Name und Kurzname der App, z. B. für Links (`"/a/" + app.slug + "/p/seite/"`) |
| `app.t("Text")` | – | Text in der Sprache der Person aus den [Übersetzungen](#übersetzungen) der App, sonst unverändert |
| `user` | `user` | angemeldete Person: `name`, `username`, `email`, `groups`, `language` (z. B. `"de"`, `"en"`; zeitgesteuert: `None`) |
| `event`, `params` | `event`, `params` | Auslöser und Parameter der Adresse (`?linie=3` → `params["linie"]`); Button-Skripte bekommen die Parameter der Seite, auf der der Button steht |
| `record` | – | der gespeicherte Eintrag (nur „nach dem Speichern“) |

Einträge sind Dictionaries mit `id`, den Kurznamen der Felder, `created_at` und
`updated_at`.

**Was Python-Skripte dürfen.** Python-Skripte laufen in einem eigenen Prozess
mit [RestrictedPython](https://restrictedpython.readthedocs.io/). Erlaubt sind
die üblichen Sprachmittel, eigene Funktionen und Klassen sowie die Module
`math`, `statistics`, `datetime`, `json`, `re`, `random`, `string`, `decimal`,
`collections`, `itertools`, `functools` und `time`. Nicht erlaubt sind Dateien, andere
Module, `eval`/`exec` und Namen, die mit `_` beginnen. Zugriff auf Daten gibt es
nur über die Befehle oben, und nur auf die eigene App. Ein Lauf darf höchstens
10 Sekunden dauern, 512 MB Speicher belegen und 1.000 Befehle absetzen
(einstellbar, siehe [Konfiguration](#konfiguration)).

**Was JavaScript-Skripte dürfen.** JavaScript läuft im Browser der Person, die
die Seite öffnet, und mit ihren Rechten: Was sie in der Oberfläche nicht darf,
darf ihr Skript auch nicht. Der Code läuft abgeschottet (Sandbox-iframe mit
eigenem Worker): Er sieht weder die Seite noch Cookies und kann keine
Verbindungen ins Netz aufbauen. Freie SQL-Abfragen und Web-Requests gibt es
deshalb nur in Python. Der Code ist für alle, die die Seite öffnen, im Browser
lesbar: keine Passwörter oder Schlüssel hineinschreiben.

**Fehler.** Ein Fehler bricht nur das Skript ab, nie die Seite. Designer sehen
ihn auf der Seite mit Zeilennummer und einem Link zum Skript, andere Nutzer
nicht. Die letzten 20 Läufe stehen im Editor; bei Seitenaufrufen werden nur
fehlgeschlagene Läufe protokolliert.

### Python-Bibliothek (baukasten-client)

Für Programme außerhalb des Baukastens, etwa Auswertungen in Jupyter, Excel-
Importe oder andere Dienste, gibt es eine Python-Bibliothek ohne weitere
Abhängigkeiten. Sie spricht die [API](#api) an und hat dieselben Befehle wie die
Skripte, damit sich Code zwischen beiden übertragen lässt.

```
pip install ./clients/python
```

```python
from baukasten_client import Client, BaukastenError

bk = Client("https://baukasten.example.com", app="inventar", key="bk_…")
geraete = bk.table("gerate")

print(geraete.count(kategorie="IT"))
for g in geraete.iter(aktiv=True):          # lädt seitenweise nach
    print(g["bezeichnung"], g["preis"])

neu = geraete.create(bezeichnung="Kamera", kategorie="IT", preis=499.5)
geraete.update(neu["id"], standort="Lager")

try:
    geraete.create(kategorie="Unbekannt")
except BaukastenError as e:
    print(e.status, e.fields)               # 400 und die Fehler je Feld
```

Weitere Befehle: `bk.describe()` (Tabellen und Felder), `.replace(id, daten)`
(Eintrag vollständig ersetzen), `bk.call("name", …)` (eigener Endpunkt). Bei
einem Server mit Zertifikat einer internen Zertifizierungsstelle:
`Client(…, cafile="firmen-ca.pem")`. Einzelheiten stehen in
`clients/python/README.md`.

### Einen Baustein in den Kern aufnehmen

Ein neuer Standard-Baustein besteht aus drei Teilen:

1. `register(...)` in `builder/blocks.py`: Name, Einstellungen, Gruppe und eine
   `prep_…`-Funktion, die die Daten für die Anzeige liefert.
2. einem Zweig in `builder/templates/builder/block.html`.
3. optional einem Symbol in `ICONS` in `static/builder/designer.js`.

Der Test `test_every_block_type_renders` prüft automatisch, dass sich jeder
registrierte Baustein fehlerfrei anzeigen lässt.

### Übersetzungen pflegen

Deutsch ist die Ausgangssprache im Code. Texte werden mit `gettext` (Python),
`{% translate %}` (Vorlagen) und `gettext()` (JavaScript) markiert. Nach
Textänderungen, im Ordner `builder/`:

```
django-admin makemessages -l en -d django
django-admin makemessages -l en -d djangojs --ignore "static/builder/swagger/*"
(Übersetzungen in locale/en/LC_MESSAGES/*.po eintragen)
django-admin compilemessages
```

Dafür muss GNU gettext installiert sein. Die kompilierten `.mo`-Dateien liegen
im Repository, im Container ist gettext nicht nötig. Eine weitere Sprache kommt
über `LANGUAGES` in `config/settings.py` und einen neuen Ordner unter
`locale/` dazu; der Sprachumschalter in `templates/builder/_language.html`
braucht dann einen weiteren Knopf.

---

## 4. Betreiben

### Konfiguration

Alles Umgebungsabhängige kommt aus Umgebungsvariablen.

| Variable | Bedeutung |
|---|---|
| `SECRET_KEY` | langer Zufallswert; Pflicht, sobald `DEBUG` nicht gesetzt ist |
| `DATABASE_URL` | z. B. `postgres://user:pass@host:5432/baukasten`; ohne Angabe SQLite |
| `ALLOWED_HOSTS` | Hostnamen der Anwendung, kommagetrennt |
| `CSRF_TRUSTED_ORIGINS` | z. B. `https://baukasten.example.com` |
| `HTTP_ALLOWED_HOSTS` | Hosts, die Web-Requests erreichen dürfen, kommagetrennt |
| `HTTP_TIMEOUT` | Zeitlimit für Web-Requests in Sekunden, Standard 10 |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | Anmeldung über Keycloak, siehe unten |
| `OIDC_ONLY` | `1` blendet die lokale Anmeldung aus |
| `OIDC_GROUPS_CLAIM` | Name der Angabe mit den Gruppen, Standard `groups` |
| `OIDC_DESIGNER_ROLE` | Rolle für den Designer, Standard `baukasten-designer` |
| `DATASOURCE_<NAME>` | eine Datenquelle, siehe [Datenquellen einrichten](#datenquellen-einrichten) |
| `SCRIPT_TIMEOUT` | Zeitlimit für Python-Skripte in Sekunden, Standard 10 |
| `SCRIPT_MEMORY_MB` | Speichergrenze je Python-Skript (nur Linux), Standard 512 |
| `SCRIPT_MAX_CALLS` | Befehle je Skriptlauf, Standard 1000 |
| `PUBLIC_RATE` | Anfragen von Gästen auf öffentlichen Seiten je Adresse und Minute, Standard 120, 0 = keine Grenze |
| `DEFAULT_USER_GROUPS` | Gruppen, zu denen jede Person automatisch gehört, Standard `Viewer` |
| `REDIS_URL` | gemeinsamer Zwischenspeicher in Redis; leer = Tabelle in PostgreSQL, siehe [Skalierung](#skalierung-und-last) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | Prozesse und Threads je Pod, Standard 3, 4 und 60 s |
| `DB_CONN_MAX_AGE` | wie lange Datenbankverbindungen offen bleiben, Standard 60 s |
| `QUERY_TIMEOUT` | Zeitlimit für Abfragen, auf die eine Seite wartet, Standard 25 s |
| `SYNC_TIMEOUT` | Zeitlimit für das Spiegeln im Hintergrund, Standard 300 s |
| `QUERY_PARALLEL` | gleichzeitige Abfragen je Datenquelle im ganzen Cluster, Standard 4 |
| `QUERY_PARALLEL_<NAME>` | dasselbe für eine einzelne Quelle, z. B. `QUERY_PARALLEL_DWH=2` |
| `QUERY_WAIT` | Sekunden, die eine Anfrage auf einen freien Platz wartet, Standard 2 |
| `LAZY_QUERIES` | `false` lädt Abfrage-Bausteine direkt mit der Seite statt danach |
| `LOG_LEVEL` | Standard `INFO` |
| `DEBUG` | nur lokal auf `1` |

### Lokal mit Kubernetes (Docker Desktop)

Zum Ausprobieren der Kubernetes-Installation auf dem eigenen Rechner:

1. In Docker Desktop unter „Kubernetes“ einen Cluster anlegen, Typ **Kubeadm**
   (ein Knoten, nutzt die lokal gebauten Images direkt).
2. Im Baukasten-Ordner ausführen:
   ```
   powershell -ExecutionPolicy Bypass -File k8s\lokal\deploy.ps1
   ```
3. http://localhost:8080 öffnen, mit `admin` anmelden. Das Passwort steht in
   `k8s\lokal\geheim.env` (`ADMIN_PASSWORD`).

Das Skript baut das Image, legt beim ersten Lauf Zufalls-Zugangsdaten an,
startet PostgreSQL im Cluster, migriert, rollt aus und legt die Beispiel-Apps an.
Für ein Update dasselbe Skript noch einmal ausführen. Es nutzt dieselben
Manifeste wie die Produktion; was lokal anders ist (kein TLS, Dienst auf
localhost:8080, keine Registry), steht in `k8s/lokal/kustomization.yaml`.
Protokoll des letzten Laufs: `k8s\lokal\letzter-lauf.log`. Alles wieder
entfernen: `kubectl delete namespace baukasten`.

### Kubernetes

Die Anwendung ist zustandslos: Sitzungen und Daten liegen in der Datenbank.
Mehrere Replicas laufen ohne Sticky Sessions.

```
docker build -t registry.example.com/baukasten:1.0.0 .
docker push registry.example.com/baukasten:1.0.0

kubectl apply -f k8s/secret.yaml          (aus secret.example.yaml erstellen)
kubectl apply -f k8s/migrate-job.yaml     (legt Tabellen an bzw. aktualisiert sie)
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/cronjob.yaml         (Hintergrundarbeiten, siehe unten)
kubectl exec deploy/baukasten -- python manage.py createsuperuser
```

Vorher in den Manifesten Image, Hostname und Ingress-Klasse anpassen. Bei jeder
neuen Version zuerst den Migrations-Job, dann das Deployment ausrollen.
`/healthz` beantwortet die Probes. TLS und die Weiterleitung von http auf https
übernimmt der Ingress.

### Skalierung und Last

**Grundsatz:** Alle Apps laufen gemeinsam in denselben Pods; eine App ist
Daten, kein eigener Dienst. Wie viele Pods laufen, hängt von der Gesamtlast ab,
nicht von der Zahl der Apps. Der Zustand liegt vollständig in PostgreSQL und im
Zwischenspeicher, daher kann jeder Pod jede Anfrage beantworten.

**Gleichzeitige Anfragen.** gunicorn läuft mit Threads (`gunicorn.conf.py`):
je Pod `GUNICORN_WORKERS × GUNICORN_THREADS` gleichzeitige Anfragen, Standard
3 × 4 = 12. Mehr Pods gibt es automatisch über den HorizontalPodAutoscaler in
`k8s/app.yaml` (2 bis 6 Pods bei 70 % CPU). Updates rollen ohne Ausfall aus
(erst neuer Pod, dann alter weg), und bei Wartung der Knoten bleibt immer ein Pod
erreichbar.

**Datenbankverbindungen mitrechnen.** Jeder Thread hält eine Verbindung zu
PostgreSQL. Grob: höchstens Pods × Workers × Threads + 5 für den Hintergrund.
Mit den Standardwerten und 6 Pods sind das 6 × 3 × 4 + 5 = 77; PostgreSQL
erlaubt standardmäßig 100. Wer mehr Pods oder Threads einstellt, erhöht
`max_connections` oder setzt einen Verbindungs-Pool wie PgBouncer davor.

**Zwischenspeicher.** Ohne weitere Einstellung liegt er in einer Tabelle der
eigenen Datenbank (`baukasten_cache`, legt der Migrations-Job an). Das reicht
für den Anfang und braucht keinen zusätzlichen Dienst. Bei vielen Pods und
vielen Live-Abfragen ist Redis schneller: `k8s/redis.yaml` einspielen oder
einen vorhandenen Redis nutzen und `REDIS_URL` im Secret setzen. Der Cache ist
nur Zwischenspeicher; fällt er aus, gehen keine Daten verloren.

**Externe Datenquellen unter Last.** Drei Schutzmechanismen sorgen dafür, dass
eine langsame Quelle (typisch: Databricks) nicht den ganzen Baukasten
ausbremst:

| Mechanismus | Wirkung | Einstellung |
|---|---|---|
| Nachladen | Seiten erscheinen sofort; Abfrage-Bausteine laden danach. Ein Baustein, der warten müsste, belegt keinen Thread, sondern der Browser fragt nach 2 Sekunden erneut. | `LAZY_QUERIES` |
| Gemeinsames Ergebnis | Dieselbe Abfrage läuft im ganzen Cluster nur einmal gleichzeitig; alle anderen bekommen ihr Ergebnis oder den letzten Stand. Bei Fehlern wird bis zu 24 Stunden der letzte Stand gezeigt. | „Ergebnis zwischenspeichern“ je Abfrage |
| Limit je Quelle | Höchstens so viele Abfragen gleichzeitig je Quelle, über alle Pods. Wer keinen Platz bekommt, erhält „ausgelastet“ statt zu warten. | `QUERY_PARALLEL`, `QUERY_PARALLEL_<NAME>`, `QUERY_WAIT` |
| Zeitlimits | Seiten warten höchstens `QUERY_TIMEOUT` (25 s). Das Spiegeln im Hintergrund darf `SYNC_TIMEOUT` (300 s) brauchen. | `QUERY_TIMEOUT`, `SYNC_TIMEOUT` |

`GUNICORN_TIMEOUT` muss über `QUERY_TIMEOUT` liegen. `QUERY_PARALLEL` richtet
sich nach dem, was die Quelle verträgt: Für ein kleines Databricks-Warehouse sind
2 bis 4 sinnvoll, für eine PostgreSQL-Replik eher 10.

**Gemessen** mit einem Pod (2 Worker × 4 Threads), Cache in PostgreSQL und
einer Datenquelle, deren Abfragen je 3 Sekunden dauern, Limit 2 gleichzeitig:
40 Personen öffnen gleichzeitig 10 verschiedene Live-Seiten.

| | ohne letzten Stand im Cache | mit letztem Stand |
|---|---|---|
| Seite sichtbar | nach 0,2 s | nach 0,2 s |
| Daten da | Median 17 s, spätestens 32 s | Median 0,4 s, spätestens 3,4 s |
| eine andere Seite nebenbei | Median 16 ms, 95 % unter 25 ms | Median 18 ms, 95 % unter 40 ms |
| Abfragen gleichzeitig an der Quelle | höchstens 2 | höchstens 2 |

Ohne Cache dauert es länger, weil die Quelle bewusst nur 2 Abfragen gleichzeitig
bekommt (10 × 3 s ÷ 2 = mindestens 15 s). Wichtig ist: Der Rest des Baukastens
bleibt dabei schnell, und die Quelle wird nie überlastet.

**Wann eine eigene Installation?** Muss eine App hart von den anderen getrennt
sein (geschäftskritisch, sehr viel Last, besondere Datenregeln), bekommt sie ein
eigenes Baukasten-Deployment mit eigener Datenbank: dasselbe Image, zweimal
installiert. Für alles andere ist die gemeinsame Installation einfacher und
günstiger.

### Datenquellen einrichten

Jede Datenquelle ist eine Umgebungsvariable `DATASOURCE_<NAME>` mit einer
Verbindungsadresse. Der Teil nach `DATASOURCE_` wird in Kleinbuchstaben zum
Namen, den Designer auswählen. Die Adressen enthalten Zugangsdaten und gehören
deshalb ins Kubernetes-Secret (`k8s/secret.example.yaml`).

```
DATASOURCE_LAGER=postgresql://leser:PASSWORT@db.example.com:5432/lager
DATASOURCE_DWH=databricks://token:dapi…@adb-123.azuredatabricks.net/sql/1.0/warehouses/abc?catalog=main&schema=werk
DATASOURCE_ALT=mssql://leser:PASSWORT@sql.example.com:1433/alt?driver=ODBC+Driver+18+for+SQL+Server
DATASOURCE_SHOP=mysql://leser:PASSWORT@mysql.example.com:3306/shop
```

Sonderzeichen in Passwort oder Token müssen URL-kodiert werden (`/` als `%2F`,
`@` als `%40`).

| Art | Treiber | Hinweis |
|---|---|---|
| PostgreSQL | `psycopg`, enthalten | Sitzung wird nur lesend geöffnet |
| Databricks | `databricks-sql-connector`, enthalten | Server-Hostname und HTTP-Pfad aus den Verbindungsdetails des SQL-Warehouse; Token eines Service Principal mit Leserechten; zusätzliche Grenze für das Zeitlimit mit `&timeout=Sekunden` |
| SQL Server | `pyodbc` plus ODBC-Treiber 18, **nicht enthalten** | im Dockerfile nachinstallieren; Verbindung mit `ApplicationIntent=ReadOnly` |
| MySQL | `pymysql`, **nicht enthalten** | `pip install pymysql` |

**Wichtig:** Der Baukasten lässt nur Abfragen zu, die mit `SELECT` oder `WITH`
beginnen, und weist verändernde Befehle zurück. Diese Prüfung ist eine
Absicherung, kein Ersatz für Rechte: Lege für jede Datenquelle einen
Datenbank-Benutzer an, der **nur lesen** darf, und nur die Tabellen, die
gebraucht werden. Jede Abfrage hat ein Zeitlimit: 25 Sekunden für Seiten
(`QUERY_TIMEOUT`), 300 Sekunden beim Spiegeln (`SYNC_TIMEOUT`); bei Databricks
begrenzt `&timeout=` in der Adresse zusätzlich. Live-Ergebnisse sind auf 2.000 Zeilen begrenzt, gespiegelte auf 50.000.

Alle Designer können alle Datenquellen nutzen. Die Ergebnisse gespeicherter
Abfragen kann jede Person sehen, die die App benutzen darf.

### Hintergrundarbeiten

Zeitgesteuerte Skripte und das Spiegeln von Abfragen erledigt der Befehl
`python manage.py hintergrund`. In Kubernetes ruft ihn der CronJob
`k8s/cronjob.yaml` jede Minute auf; jedes Skript und jede Abfrage hat
zusätzlich ein eigenes Intervall. `concurrencyPolicy: Forbid` sorgt dafür, dass
nie zwei Läufe gleichzeitig arbeiten. Fehler stehen im Protokoll des Jobs und in
der App (bei Skripten unter „Letzte Läufe“, bei Abfragen unter „Letzter Abgleich“).

### Anmeldung über Keycloak

Ohne `OIDC_`-Variablen melden sich Nutzer mit lokalen Konten an (Verwaltung
unter `/admin/`). Mit den Variablen zeigt die Anmeldeseite „Mit Firmenkonto
anmelden“.

In Keycloak:

1. Einen Client vom Typ „OpenID Connect“ mit Client-Authentifizierung anlegen.
2. Gültige Weiterleitungsadresse: `https://<host>/oidc/callback/`. Adresse nach
   dem Abmelden: `https://<host>/`.
3. Dem Client einen Mapper „Group Membership“ mit dem Namen `groups` geben und
   „Add to userinfo“ einschalten, damit Gruppen ankommen.
4. Die Rolle `baukasten-designer` anlegen und den Personen zuweisen, die Apps
   bauen.

Im Baukasten: `OIDC_ISSUER` ist die Adresse des Realms, zum Beispiel
`https://keycloak.example.com/realms/firma`. Client-ID und Secret kommen aus
dem Client.

Beim ersten Login wird der Nutzer angelegt. Name, E-Mail, Gruppen und die
Designer-Rolle werden bei **jedem** Login aus Keycloak übernommen; wer die Rolle
dort verliert, verliert sie beim nächsten Login auch hier. Ein lokales Konto mit
Passwort wird nie von einem gleichnamigen Keycloak-Konto übernommen.

### Rechte

| Wer | Darf |
|---|---|
| Nutzer | veröffentlichte Apps verwenden, die für alle oder für eine seiner Gruppen freigegeben sind |
| Designer | eigene Apps und Apps, zu denen sie eingeladen sind, bearbeiten; neue Apps anlegen, eigene Bausteine anlegen |
| Verwalter (Superuser) | zusätzlich alle Apps im Designer und `/admin/`: Benutzer, Gruppen, alle Daten |

Designer ist, wer in Keycloak die Designer-Rolle hat, oder lokal das Recht
„Darf Apps im Designer bearbeiten“ bzw. den Mitarbeiter-Status.

**Eigentümerin und Mitbearbeiter.** Wer eine App anlegt, ist ihre
Eigentümerin. Im Designer der App, Abschnitt „Mitbearbeiter“:

- Die Eigentümerin lädt Designer per Benutzername ein oder fügt eine Gruppe
  hinzu. Eingeladene brauchen das Designer-Recht; Gruppenmitglieder ohne dieses
  Recht können die App nicht bearbeiten.
- Mitbearbeiter dürfen alles an der App ändern, außer die Mitbearbeiter selbst,
  und sie dürfen die App nicht löschen. Das dürfen nur Eigentümerin und
  Verwalter.
- Andere Designer sehen die App im Designer nicht. Benutzen dürfen sie sie wie
  alle anderen, wenn sie veröffentlicht und für ihre Gruppe freigegeben ist.
- Apps ohne Eigentümerin (vor dieser Funktion angelegt oder deren Konto
  gelöscht wurde) bleiben wie bisher für alle Designer offen, auch zum Löschen.
  Jeder Designer kann so eine
  App mit „App übernehmen“ an sich nehmen; danach brauchen andere eine
  Einladung.
- Die Eigentümerin wechseln Verwalter unter `/admin/` → Apps.

**Standardgruppen.** Jede Person gehört automatisch zur Gruppe **Viewer**: beim
Anlegen, bei jeder Anmeldung und beim Abgleich mit Keycloak. Bestehende Nutzer
wurden beim Update aufgenommen. Welche Gruppen das sind, legt die Einstellung
`DEFAULT_USER_GROUPS` fest (kommagetrennt, leer = keine). Was die Gruppe darf,
bestimmen ihre Rechte unter `/admin/` → Gruppen. Eine App, die auf „Viewer“
beschränkt ist, ist damit für alle angemeldeten Personen offen.

Die Leserechte einer Gruppe („Kann … ansehen“) wirken nur in der Verwaltung
unter `/admin/`, und die erreicht nur, wer zusätzlich den Mitarbeiter-Status hat.
Gib einer Standardgruppe dort keine Rechte für Benutzer und Sitzungen, sonst
sieht jede Person mit Mitarbeiter-Status Daten anderer Personen.

### Verwaltung (/admin/)

Die Verwaltung ist nach Apps geordnet:

- **Startseite:** oben eine Tabelle aller Apps mit Zahl der Tabellen,
  Einträge, Seiten und Skripte, und „Daten ansehen“.
- **Daten ansehen:** zeigt jede Tabelle einer App mit echten Spalten, je 50
  Einträge pro Seite, die neuesten zuerst. Ein Klick auf die Nummer öffnet den
  Eintrag.
- **Eine App öffnen** zeigt ihre Tabellen (mit Link auf die Einträge), Seiten,
  Skripte, Abfragen, API-Schlüssel und Versionen auf einer Seite.
- **Listen** (Einträge, Felder, Skripte, Skriptläufe, Abfragen, Schlüssel,
  Versionen) lassen sich rechts nach **App** filtern, Einträge zusätzlich nach
  Tabelle. Die Suche bei Einträgen durchsucht den gesamten Inhalt.
- **Ein Eintrag** zeigt oben seine Felder lesbar und darunter den Inhalt als
  JSON zum Bearbeiten.

Apps, Tabellen, Felder und Seiten baust du besser im Designer: Dort werden
Eingaben geprüft und Seiten bleiben stimmig. Die Verwaltung ist für den
Überblick, für Korrekturen und für Benutzer und Gruppen gedacht.

### Firmenlogo und Design

- **Logo:** Die offizielle Logo-Datei als `logo.svg` oder `logo.png` nach
  `builder/static/builder/brand/` legen. Sie erscheint in der Kopfzeile und auf
  der Anmeldeseite. Hinweise stehen in der Datei `LIESMICH.txt` in diesem
  Ordner. Ein Logo liegt bewusst nicht bei: Verwende die Originaldatei aus dem
  Marken-Portal und beachte dessen Vorgaben.
- **Farben, Schrift, Rundungen:** stehen als Variablen in
  `builder/static/builder/theme.css`. Ein Firmen-Stylesheet lässt sich in
  `templates/base.html` nach `theme.css` einbinden. Die Farben für den Dunkelmodus stehen
  in derselben Datei im Block `html[data-theme="dark"]` (und noch einmal für
  „Automatisch“ in `@media (prefers-color-scheme: dark)`); wer Farben ändert,
  ändert beide Fassungen.
- **Schrift:** IBM Plex Sans liegt lokal bei (SIL Open Font License). Es wird
  nichts aus dem Internet geladen.

Nach Änderungen an statischen Dateien muss das Image neu gebaut werden
(`collectstatic` läuft im Dockerfile).

### Sicherheit

- **Anmeldung** ist für alle Seiten Pflicht. Die API verlangt einen Schlüssel.
- **Rechte** werden auf dem Server geprüft: Zugriff auf Apps, Designer-Recht,
  Anlegen/Bearbeiten/Löschen je Tabelle, Schreibrecht des API-Schlüssels.
- **Eingaben** werden in Vorlagen automatisch maskiert. HTML eigener Bausteine
  wird bereinigt (siehe oben). Der CSV-Export entschärft Zellen, die Excel als
  Formel ausführen würde.
- **Web-Requests** gehen nur an freigegebene Hosts (`HTTP_ALLOWED_HOSTS`),
  damit über den Designer keine internen Adressen abgefragt werden können.
- **API-Schlüssel** werden nur als Hash gespeichert.
- **Python-Erweiterungen** laufen mit allen Rechten der Anwendung. In den
  Ordner `extensions/` gehört nur geprüfter Code.
- **Python-Skripte aus dem Designer** laufen dagegen abgeschottet: eigener
  Prozess ohne Umgebungsvariablen (also ohne Passwörter, Schlüssel und
  Datenbankzugang), RestrictedPython, Zeit- und unter Linux Speicher- und
  Dateigrenzen. Daten erreichen sie nur über die Befehle des Baukastens und nur
  in ihrer App. Restrisiko: Ein Fehler in RestrictedPython könnte einem Skript
  mehr erlauben. Wer sich davor schützen muss, lässt Skripte in einem eigenen
  Container ohne Netzwerkzugang laufen; das ist noch nicht eingebaut.
- **JavaScript-Skripte** laufen im Browser in einer Sandbox ohne Zugriff auf die
  Seite, auf Cookies und auf das Netz, mit den Rechten der jeweiligen Person.
- **Datenquellen:** Zugangsdaten nur in Umgebungsvariablen bzw. Secrets; sie
  erscheinen nie in der Oberfläche und werden aus Fehlermeldungen entfernt.
  Nur-Lese-Benutzer in der Datenbank sind Pflicht.
- **Nicht enthalten:** eine Begrenzung der Anfragen pro Zeit (für die API am
  Ingress einrichten) und ein Protokoll, wer wann was geändert hat.

### Sicherung

Alle Inhalte liegen in der Datenbank: Apps, Daten, Versionen, Benutzer. Eine
regelmäßige Datenbanksicherung genügt. Versionen ersetzen sie nicht, denn sie
enthalten keine Daten.

---

## Häufige Fragen

**Ich sehe eine App nicht, die es geben müsste.**
Entweder ist sie noch nicht veröffentlicht, oder sie ist auf Gruppen beschränkt,
in denen du nicht bist. Dein Profil zeigt deine Gruppen; wer die App gebaut hat,
sieht unter „Einstellungen und Freigabe“, für wen sie freigegeben ist.

**Ich sehe den Link „Designer“ nicht.**
Dir fehlt das Designer-Recht. Mit Firmenkonto vergibt es Keycloak über die
Rolle `baukasten-designer`, sonst die Verwaltung.

**Ich habe aus Versehen etwas an einer Seite kaputt gemacht.**
Wenn eine Version gespeichert ist: in der App unter „Versionen“ wiederherstellen.
Daten gehen dabei nicht verloren. Ohne Version lässt sich der Aufbau nicht
zurückholen; speichere deshalb vor größeren Umbauten eine Version.

**Ein Baustein zeigt einen rot umrandeten Hinweis.**
Ihm fehlt eine Einstellung, meist die Tabelle oder das Feld, oder die Tabelle
wurde gelöscht. Im Seiten-Designer anklicken und rechts nachtragen.

**Ein Skript meldet einen Fehler.**
Designer sehen den Fehler auf der Seite mit Zeilennummer und Link. Im Editor
„Speichern und testen“ zeigt Ausgabe und Fehler; „Letzte Läufe“ und dein Profil
listen frühere Fehler. Andere Nutzer sehen keine Skriptfehler, nur dass der
Baustein leer bleibt.

**Die Live-Daten aus Databricks laden sehr langsam.**
Vermutlich schläft das SQL-Warehouse und muss erst starten. Für Live-Anzeigen
ein laufendes Warehouse nehmen oder die Abfrage in eine Tabelle spiegeln.

**Ein Abfrage-Baustein zeigt „wird gerade geladen“ oder „ausgelastet“.**
Die Datenquelle bekommt gerade so viele Abfragen, wie der Betrieb erlaubt. Der
Baustein versucht es von selbst wieder. Passiert das oft: „Ergebnis
zwischenspeichern“ erhöhen, die Abfrage spiegeln oder den Betrieb bitten,
`QUERY_PARALLEL` für diese Quelle anzupassen.

**Mein API-Aufruf liefert 401.**
Der Schlüssel fehlt, ist falsch oder gehört zu einer anderen App. Er muss im
Kopf `Authorization: Bearer bk_…` stehen. Bei **403** darf der Schlüssel nur
lesen oder die Tabelle erlaubt die Aktion nicht, bei **404** ist die Tabelle
nicht freigeschaltet.

**Ich habe meinen API-Schlüssel nicht kopiert.**
Er lässt sich nicht wieder anzeigen. Lösche ihn (im Profil oder in der App) und
erzeuge einen neuen.

**Wie bekomme ich Daten nach Excel?**
Einmalig: Baustein „CSV-Export“ auf eine Seite setzen und herunterladen.
Regelmäßig: Power Query in Excel mit der API, oder die Python-Bibliothek.

**Wo sehe ich alle Daten einer App auf einen Blick?**
Als Verwalter unter `/admin/` → bei der App „Daten ansehen“.

## Grenzen des jetzigen Stands

- **Getestet** mit SQLite: 111 automatische Tests und Durchläufe im Browser
  (Chrome), darunter Python- und JavaScript-Skripte, Live-Anzeige und Spiegeln
  mit einer SQLite-Datenquelle sowie die Python-Bibliothek gegen einen echten
  Server. Mit PostgreSQL (für den Baukasten und als Datenquelle) und gunicorn
  wie im Container lief der Lasttest aus [Skalierung](#skalierung-und-last),
  einmal mit dem Cache in PostgreSQL und einmal mit Redis.
  **Nicht getestet:** der Docker-Build, die
  Kubernetes-Manifeste auf einem echten Cluster, der vollständige Login gegen
  einen echten Keycloak und Verbindungen zu echten Datenbanken außer SQLite. Für
  Databricks ist nur geprüft, wie die Adresse an den Treiber übergeben wird und
  wie Fehler ankommen; eine Verbindung zu einem echten Warehouse fehlt.
- **Skripte:** Jeder Python-Lauf startet einen eigenen Prozess (etwa 0,1 bis
  0,3 Sekunden). Skripte beim Seitenaufruf machen die Seite entsprechend
  langsamer. JavaScript-Skripte brauchen einen aktuellen Browser.
- **Datenquellen:** werden vom Betrieb über Umgebungsvariablen eingerichtet,
  nicht im Designer; alle Designer können alle Quellen nutzen. Gespiegelte
  Tabellen lösen keine Skripte „nach dem Speichern“ aus.
- **Rechte** gelten pro App und pro Tabelle, nicht pro Seite, Eintrag oder
  Feld. Wer eine App benutzen darf, sieht alle ihre Seiten. Im Designer gibt es
  nur „darf die ganze App bearbeiten“, keine Rechte je Seite oder Skript.
  Eigene Bausteine und Vorlagen gelten weiterhin für alle Designer.
- **Gleichzeitiges Bearbeiten:** Speichern zwei Mitbearbeiter dieselbe Seite
  oder dasselbe Skript, gilt die zuletzt gespeicherte Fassung, ohne Warnung.
- **Versionen** entstehen nur auf Knopfdruck und enthalten keine Daten.
  Tabellen werden beim Wiederherstellen nie gelöscht.
- **API:** keine Begrenzung der Anfragen pro Zeit, keine Sortierung, Filter nur
  auf Gleichheit.
- **Führung:** Ob jemand sie gesehen hat, merkt sich der Browser, nicht der
  Server.
- **Übersetzung:** Oberfläche auf Deutsch und Englisch; Inhalte von Apps und die
  Platzhalter `nutzer`, `app`, `datum` sind einsprachig. Dieses Handbuch gibt es
  nur auf Deutsch.
- **Zugänglichkeit:** Tastaturbedienung und Beschriftungen sind berücksichtigt,
  eine Prüfung nach einem Standard (z. B. WCAG) hat nicht stattgefunden. Das
  Ziehen im Seiten-Designer braucht eine Maus; als Ersatz gibt es Anklicken und
  „Nach vorn“ / „Nach hinten“.

## Glossar

| Begriff | Bedeutung |
|---|---|
| App | eine Anwendung im Baukasten, bestehend aus Tabellen und Seiten |
| Tabelle | eine Art von Einträgen, zum Beispiel „Geräte“ |
| Feld | eine Angabe pro Eintrag, zum Beispiel „Preis“ |
| Eintrag | ein Datensatz in einer Tabelle |
| Seite | das, was Nutzer sehen; besteht aus Bausteinen |
| Baustein | ein Element einer Seite, zum Beispiel Liste oder Kennzahl |
| Vorlage | ein fertig eingestellter Baustein zum Wiederverwenden |
| Kurzname | technischer Name in Adressen, API und Code, zum Beispiel `gerate` |
| Version | gespeicherter Aufbau einer App, ohne Daten |
| Designer | Bereich zum Bauen von Apps; auch die Rolle der Personen, die das dürfen |
| Standardgruppe | Gruppe, zu der jede Person automatisch gehört (Viewer) |
| OpenAPI, Swagger | Standard für API-Beschreibungen bzw. die Oberfläche, die sie anzeigt und ausprobierbar macht |
| Verwaltung | der Bereich unter `/admin/` für Benutzer, Gruppen und den Überblick über alle Daten |
| Datenquelle | eine vom Betrieb eingerichtete externe Datenbank, z. B. ein Databricks SQL-Warehouse |
| Abfrage | gespeichertes SQL gegen eine Datenquelle, live angezeigt oder gespiegelt |
| Spiegeln | Ergebnis einer Abfrage regelmäßig in eine Tabelle übernehmen |
| Skript | Python- oder JavaScript-Code, der zu einem Auslöser läuft |
