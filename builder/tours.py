"""Texte der Führungen für neue Nutzer.

Jede Führung ist eine Liste von Schritten. „target“ ist ein CSS-Selektor des
Elements, das hervorgehoben wird; ohne „target“ steht der Hinweis in der Mitte.
Schritte, deren Element auf der Seite fehlt, werden übersprungen.
"""
from django.utils.translation import gettext_lazy as _

TOURS = {
    "start": [
        {"title": _("Willkommen im Baukasten"),
         "text": _("Hier arbeitest du mit Apps, die bei euch gebaut wurden. Die Führung zeigt dir in einer Minute, wo was ist.")},
        {"target": "[data-tour=apps]", "title": _("Deine Apps"),
         "text": _("Jede Kachel ist eine App. Ein Klick öffnet sie. Du siehst nur Apps, die für dich freigegeben sind.")},
        {"target": "[data-tour=brand]", "title": _("Zurück zur Übersicht"),
         "text": _("Über das Logo kommst du von überall wieder auf diese Seite.")},
        {"target": "[data-tour=designer-link]", "title": _("Designer"),
         "text": _("Hier baust und änderst du Apps: Daten festlegen, Seiten zusammenstellen, freigeben.")},
        {"target": "[data-tour=language]", "title": _("Sprache"),
         "text": _("Die Oberfläche gibt es auf Deutsch und Englisch. Hier wechselst du.")},
        {"target": "#tour-start", "title": _("Führung erneut starten"),
         "text": _("Auf Seiten mit einer Führung startet das Fragezeichen sie erneut.")},
    ],
    "designer": [
        {"title": _("So entsteht eine App"),
         "text": _("In drei Schritten: Erstens Daten festlegen (Tabellen und Felder). Zweitens Seiten zusammenstellen. Drittens veröffentlichen. Programmieren musst du dafür nicht.")},
        {"target": "[data-tour=new-app-form]", "title": _("Neue App anlegen"),
         "text": _("Gib der App einen Namen und ein Symbol. Danach landest du direkt in ihren Einstellungen.")},
        {"target": "[data-tour=app-list]", "title": _("Vorhandene Apps"),
         "text": _("Hier findest du alle Apps wieder. „Entwurf“ heißt: nur Designer sehen sie.")},
        {"target": "[data-tour=custom-blocks]", "title": _("Eigene Bausteine"),
         "text": _("Wenn die mitgelieferten Bausteine nicht reichen, legst du hier eigene an und verwendest sie in allen Apps.")},
    ],
    "designer-app": [
        {"target": "[data-tour=entities]", "title": _("Schritt 1: Daten"),
         "text": _("Eine Tabelle beschreibt, was die App verwaltet, zum Beispiel Geräte oder Anträge. Lege eine an und gib ihr Felder.")},
        {"target": "[data-tour=pages]", "title": _("Schritt 2: Seiten"),
         "text": _("Seiten sind das, was Nutzer sehen. Du stellst sie im Seiten-Designer aus Bausteinen zusammen. Aus jeder Tabelle lässt sich auch eine fertige Seite erzeugen.")},
        {"target": "[data-tour=settings]", "title": _("Schritt 3: Freigabe"),
         "text": _("Solange „Veröffentlicht“ nicht angehakt ist, sehen nur Designer die App. Mit Gruppen beschränkst du sie auf bestimmte Nutzer.")},
        {"target": "[data-tour=api]", "title": _("Optional: API"),
         "text": _("Andere Programme können die Daten über eine Schnittstelle lesen und schreiben. Dafür schaltest du Tabellen frei und erzeugst einen Schlüssel.")},
        {"target": "[data-tour=open-app]", "title": _("Ergebnis ansehen"),
         "text": _("So sieht die App für Nutzer aus. Du kannst jederzeit hin- und herwechseln.")},
    ],
    "designer-tabelle": [
        {"target": "[data-tour=fields]", "title": _("Felder der Tabelle"),
         "text": _("Jedes Feld ist eine Angabe pro Eintrag, etwa Bezeichnung, Datum oder Preis. Das erste Feld dient als Name des Eintrags.")},
        {"target": "[data-tour=add-field]", "title": _("Feld hinzufügen"),
         "text": _("Wähle einen Typ: Text, Zahl, Datum, Ja/Nein, Auswahl aus festen Werten oder ein Verweis auf eine andere Tabelle.")},
        {"target": "[data-tour=make-page]", "title": _("Fertige Seite erzeugen"),
         "text": _("Ein Klick erzeugt eine Seite mit Liste, Suche, Anlegen, Bearbeiten und Löschen. Du kannst sie danach frei umbauen.")},
    ],
    "seiten-designer": [
        {"title": _("Der Seiten-Designer"),
         "text": _("Hier stellst du eine Seite aus Bausteinen zusammen. Links wählst du aus, in der Mitte ordnest du an, rechts stellst du ein.")},
        {"target": "#palette-panel", "title": _("Bausteine"),
         "text": _("Ziehe einen Baustein auf die Seite oder klicke ihn an. Sie sind nach Zweck gruppiert. Ganz unten stehen eigene Bausteine und Vorlagen.")},
        {"target": "#canvas", "title": _("Arbeitsfläche"),
         "text": _("Du siehst die Seite mit echten Daten. Bausteine verschiebst du per Ziehen. Ein Klick wählt einen Baustein aus.")},
        {"target": "#props", "title": _("Einstellungen"),
         "text": _("Für den gewählten Baustein: Breite, Beschriftung, welche Tabelle er zeigt. Hier kannst du ihn auch duplizieren, als Vorlage speichern oder entfernen.")},
        {"target": "[data-tour=save-area]", "title": _("Speichern und ansehen"),
         "text": _("Änderungen gelten erst nach „Speichern“. „Vorschau“ öffnet die Seite so, wie Nutzer sie sehen.")},
    ],
    "skripte": [
        {"title": _("Skripte"),
         "text": _("Ein Skript ist eigene Logik in Python oder JavaScript. Python läuft auf dem Server und darf alle Tabellen dieser App lesen und schreiben. JavaScript läuft im Browser mit den Rechten der Person, die die Seite öffnet.")},
        {"target": "[data-tour=script-trigger]", "title": _("Wann es läuft"),
         "text": _("Beim Öffnen einer Seite, per Button, nach dem Speichern eines Eintrags oder zeitgesteuert im Hintergrund. Die letzten beiden gibt es nur für Python.")},
        {"target": "[data-tour=script-code]", "title": _("Bausteine füllen"),
         "text": _("Gib einem Baustein im Seiten-Designer einen Namen. Mit ui.set(\"name\", value=…) füllt das Skript ihn. Rechts steht eine Kurzreferenz.")},
    ],
    "eigene-bausteine": [
        {"title": _("Eigene Bausteine"),
         "text": _("Ein eigener Baustein besteht aus HTML und aus Einstellungen, die du selbst festlegst. Programmieren ist dafür nicht nötig.")},
        {"target": "[data-tour=block-settings]", "title": _("Einstellungen festlegen"),
         "text": _("Jede Zeile wird zu einem Eingabefeld im Seiten-Designer. „Titel = Hallo“ erzeugt das Feld „Titel“ mit dem Standardwert „Hallo“.")},
        {"target": "[data-tour=block-html]", "title": _("HTML mit Platzhaltern"),
         "text": _("Wo im HTML {{ titel }} steht, erscheint später der eingestellte Wert. Skripte und unsichere Angaben werden beim Speichern entfernt.")},
    ],
}
