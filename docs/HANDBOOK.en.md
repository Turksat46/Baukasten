# Baukasten – Handbook

Baukasten is a tool for building internal web apps in the browser: define the
data, assemble pages from building blocks, publish. If you can program, you add
logic in Python. Technically, Baukasten is a Django application that runs on
Kubernetes.

This handbook is also available in the application: **Help** in the top right
corner. The language switch (**DE | EN**) changes between the German and the
English version.

## Where to start

| You want to … | Read |
|---|---|
| use an existing app | [1. Using apps](#1-using-apps), five minutes |
| build your first own app | the [guided introduction](#guided-introduction-your-first-app) in Baukasten, or [Quick start](#quick-start-your-first-app-in-15-minutes), then [2. Building apps](#2-building-apps) |
| show data from a database or Databricks | [Data from databases and Databricks](#data-from-databases-and-databricks) |
| access data from another program | [API](#api) and the API documentation in the application |
| show Tableau dashboards | [Tableau](#tableau) |
| connect AI agents such as n8n | [MCP server](#mcp-server-ai-agents-n8n) |
| program logic | [Scripts](#scripts) and [3. Developing](#3-developing) |
| look at finished examples | [Example apps](#example-apps) |
| try Baukasten in Kubernetes on your own computer | [Local Kubernetes](#local-kubernetes-docker-desktop) |
| install or operate Baukasten | [4. Operating](#4-operating) |
| get a quick answer | [Frequently asked questions](#frequently-asked-questions) |

## The concepts in one picture

```
Baukasten
└── App  "Inventory"                    ← an application for one purpose
    ├── Tables     "Devices", "Rooms"   ← which data exists
    │   └── Fields  Name, Price …           ← what belongs to every entry
    │       └── Entries  "Projector", "Oscilloscope" …   ← the actual data
    ├── Pages      "Overview", "Devices" ← what users see
    │   └── Blocks  List, Chart, Form …
    ├── Scripts    Python or JavaScript  ← your own logic
    ├── Queries    SQL against databases ← data from outside
    ├── API keys                         ← access for other programs
    ├── Translations                     ← the app's texts in other languages
    └── Versions                         ← saved states of the app's structure
```

## The four parts

| Part | For whom |
|---|---|
| [1. Using apps](#1-using-apps) | everyone who works with finished apps |
| [2. Building apps](#2-building-apps) | designers: business departments that create apps |
| [3. Developing](#3-developing) | developers: scripts, Python extensions, API, MCP, Python library, code structure |
| [4. Operating](#4-operating) | operations: installation, Kubernetes, data sources, Keycloak, security |

At the end you find [Frequently asked questions](#frequently-asked-questions),
[Current limitations](#current-limitations) and a [Glossary](#glossary).

---

## Example apps

| App | Shows | Create with |
|---|---|---|
| Inventar (inventory) | tables, forms, metrics, charts, data source, Python and JavaScript scripts | `python manage.py demo` |
| Aufnahme-Einwilligung (recording consent) | a process across several people: create an event, send a link, agree or decline, evaluation; also for guests without an account | `python manage.py beispiel_einwilligung` |

The example apps are built in German. With [translations](#translating-an-app)
they can also be shown in English.

**Recording consent** in detail:

- On the start page "Veranstaltungen" (events), the person responsible creates an
  event: title, date, location, type of recording and purpose.
- The script "Teilnahme-Link erzeugen" (runs after saving) fills in the link
  `/a/einwilligung/p/teilnahme/?event=<number>` and the person responsible.
  Neither field appears in the form.
- The page "Teilnahme" (participation) is not in the menu. A page script reads
  the number from the address and shows title, date, recordings, purpose and the
  previous answer of the signed-in person.
- The buttons "Ich stimme den Aufnahmen zu" (I agree) and "Ich lehne ab"
  (I decline) each start a Python script. It stores name, email, decision and
  time. There is exactly one answer per person and event; a new answer replaces
  the old one.
- **Guests without an account**, built only with Baukasten features: the script
  "Teilnahme-Link erzeugen" gives every event a secret code with `token()` and
  fills in the guest link `/a/einwilligung/p/gast/?code=<code>`. The page "Gast"
  is a [public page](#public-pages) with two input fields (name, email) and the
  buttons to agree or decline. The page script "Gast-Seite füllen" looks up the
  event for the code; the button scripts store the answer with origin "Gast" and
  remember its number in `session`. If the guest reloads the page, they see their
  decision; clicking again changes the answer instead of creating a second one.
  Everything can be changed in the Designer.
- Limits of the guest link: nobody checks whether the name is correct; whoever
  has the link can answer in someone else's name. A guest can only change their
  answer in the same browser; in another browser or after deleting cookies they
  count as a new person, and another entry is created. The guest link is valid
  until the event is deleted or the app is no longer published.
- Answers are only created through these pages: creating, editing and deleting
  are switched off in the table "Antworten" (answers).
- The start page and "Antworten" show how many agreed and declined, per event
  and as a list with CSV export.

**Important before real use:** permissions in Baukasten apply per app. Whoever
may open the participation page can also open the pages "Veranstaltungen" and
"Antworten" and thus sees who declined. For real consents, restrict the app to
the organisers or wait for permissions per page (see
[Current limitations](#current-limitations)). If the app is restricted to the
organisers, the guest link still works: public pages need no permissions for the
app, only that it is published.

## Quick start: your first app in 15 minutes

As an example you build an app for leave requests. You need the "Designer"
permission (see [Permissions](#permissions)). Prefer to be guided directly in the
interface? Start the [guided introduction](#guided-introduction-your-first-app).

**1. Create the app (1 minute).** Open "Designer" in the top right. Under "Neue
App" (new app) enter the name *Leave* and an icon, for example 🌴, then
"Anlegen" (create). You land on the app overview with three numbered boxes.

**2. Define the data (5 minutes).** In the box "1 Data: tables" create the table
*Requests*. It automatically gets the field "Bezeichnung" (name). On the right,
under "Add field", add these fields:

| Label | Type | Required |
|---|---|---|
| From | Date | yes |
| To | Date | yes |
| Days | Whole number | yes |
| Status | Choice, values: *open*, *approved*, *rejected* (one per line) | yes |

**3. Generate a page (1 minute).** Click "Generate page from this table" at the
top. The page "Requests" now has a list with search, "New", "Edit" and
"Delete". "Open app" shows it the way users see it. Create two or three requests
to try it out.

**4. Design the start page (5 minutes).** Back in the Designer, open the page
"Start". In the page designer:

- remove the text block (click it, "Remove" on the right),
- put two *metrics* next to each other, width "½" each: "Requests total"
  (count) and "Days requested" (sum of the field *Days*),
- add a *donut chart* "By status", grouped by *Status*,
- "Save".

**5. Publish (1 minute).** In the app under "3 Settings and sharing", tick
"Published". Without a selection under "Groups", all signed-in people now see
the app; with a selection only members of those groups.

**6. Save a version (30 seconds).** Under "Versions", save a version with the
note *first draft*. If a later redesign goes wrong, "Restore" brings this state
back.

That's it. Next steps, if you like: a [script](#scripts) that checks the status
after saving, or the [API](#enabling-the-api) so that Excel or another program
can read the requests.

---

## 1. Using apps

### Signing in

Open the address of Baukasten. Depending on the setup you sign in with your
company account ("Sign in with company account", via Keycloak) or with a local
user name and password.

### Home page

After signing in you see a greeting with today's date and your apps as tiles,
each with its own color and the number of pages. You only see apps that are
published and shared with you; designers also see their drafts. With more than
six apps, a search field above the tiles filters them as you type. Below the
tiles, **Quick access** leads to the handbook, your profile, the API
documentation and, for designers, custom blocks. A click on a tile opens the
app; the logo in the top left always takes you back.

### Working in an app

The pages of the app are listed at the top. What a page shows was decided by the
person who built the app. Typical are:

- **Lists:** entries with a search field. "New" creates an entry; "Edit" and
  "Delete" are at the end of each row, if allowed.
- **Forms:** capture new entries directly on the page. Required fields are
  checked when saving.
- **Evaluations:** metrics, charts, line charts and timelines. They always
  calculate with the current data.
- **CSV export:** downloads all entries of a table for Excel.
- **Tableau dashboards**, if your company uses Tableau.

### Language

The interface is available in German and English. Switch with "DE | EN" in the
top right; the choice is remembered. Without your own choice, your browser's
language applies. The Baukasten interface is translated; an app's contents
(page titles, field names, choices, block texts) appear in English only if its
designer has entered [translations](#translating-an-app). Entered data stays as
it was typed.

### Light and dark

The icon next to "DE | EN" switches the appearance: automatic (half circle,
follows the operating system), light (sun), dark (moon). The same is possible
in your profile under "Settings". The browser remembers the choice; it applies
to all pages, including the administration under `/admin/` and the API
documentation.

### Page transitions

When switching pages, Baukasten fades smoothly: the header stays in place, the
marker under the active tab moves along, and the content slides in in reading
direction (forward to the right, back to the left). This works in Chrome, Edge
and Safari; other browsers switch without animation. If "reduce motion" is
switched on in the operating system, there is no animation.

### Tour

On the first visit, a short tour starts on important pages. The question mark in
the top right starts it again. Esc ends it.

### My profile

A click on your name in the top right opens your profile. It shows everything
that belongs to you:

- **Permissions:** how many apps you may use, whether you are a designer,
  whether you may open the administration (`/admin/`), and your groups. Groups
  that every person has automatically are marked "Default".
- **My apps:** all apps you may open and those you created yourself.
- **My API keys:** every key you created, with app, permissions and last use.
  You can delete your own keys here.
- **My scripts:** with the result of the last run and the latest errors, so you
  notice problems early.
- **My queries and blocks.**
- **Settings:** language, appearance (light, dark, system), show tours again
  and, for a local account, change your password.

---

## 2. Building apps

The Designer is visible to people with the permission to use it (see
[Permissions](#permissions)). The link "Designer" is in the top right. In the
Designer you see apps you own or were invited to as a co-editor (see
[Co-editors](#owners-and-co-editors)).

### An app in three steps

1. **Create the app:** in the Designer enter name and icon, "Create".
2. **Define the data:** create a table (for example "Devices") and give it
   fields.
3. **Generate a page:** in the table click "Generate page from this table". This
   immediately gives you a list with search, create, edit and delete.

Then adjust pages in the page designer and publish the app.

### Guided introduction: your first app

The guided introduction walks you through building a leave-request app in about
20 minutes, directly in Baukasten instead of only in the handbook. Start it in
the Designer ("New here? → Start introduction") or on the home page under quick
access ("Introduction").

A **companion** then sits in the bottom right corner. It blocks nothing; you work
as usual and it shows what comes next:

| # | Step | What you learn |
|---|---|---|
| 1 | create the app "Urlaub" (name and icon are pre-filled) | creating apps |
| 2 | create the table "Anträge" (requests) | tables |
| 3 | fields From, To (date), Days (number), Status (choice) | field types |
| 4 | generate a page from the table | ready-made list pages |
| 5 | enter two requests in the app | the app from the users' point of view |
| 6 | start page with a metric and a chart | page designer, evaluations |
| 7 | "after saving" script: calculate days, set status "offen" | scripts (code to copy is included) |
| 8 | publish | sharing |
| 9 | save a version | versions |

- **"Go there"** jumps to the page where the step happens; there **"Show me
  where"** scrolls to the spot and makes it light up briefly.
- A step **ticks itself off** as soon as the app contains it. What counts is
  what is in the app, not which buttons you pressed. If you do things in a
  different order, you still move on.
- The practice app is the first app you create after starting. It is a normal
  app: keep it, change it or delete it.
- At the end the companion suggests next steps: translations, co-editors, API
  and MCP. "End introduction" hides it at any time; it can be restarted in the
  Designer.
- While the introduction runs, the short page tours do not start by themselves
  (the question mark in the top right still starts them).

### Tables and fields

A table describes one kind of entry. Each field is one piece of information per
entry. The first field serves as the entry's name, for example in references.

| Field type | Input | Note |
|---|---|---|
| Text | single line | up to 500 characters |
| Long text | multiple lines | |
| Whole number | number without decimals | usable for sum and average |
| Decimal number | number with decimals | usable for sum and average |
| Date | date picker | usable for timeline and line chart |
| Yes/No | checkbox | |
| Choice | fixed values | one value per line under "Choices" |
| Email, Link | validated input | |
| Reference to table | an entry of another table | choose the target table under "References" |

Every field has a technical short name (for example `anschaffung`). It is
derived from the label, stays fixed afterwards and is used in the API and in
Python extensions. In the Designer it is shown in grey next to the label.

For every field you can also decide whether it appears **in lists** and **in
the form**. Fields that a script fills (for example a generated link) are
switched off in the form; their value is kept when editing. Fields of type
"Link" are clickable in lists.

Per table you can switch off whether entries may be created, edited or deleted.
This applies to the interface and to the API.

**Important:** if a field is deleted, it disappears from lists and forms; values
already entered stay stored. If a table is deleted, its entries are gone for
good.

### Page designer

On the left you pick blocks, in the middle you arrange them, on the right you
configure the selected block.

- **Add:** drag a block onto the page or click it.
- **Move:** drag a block to another place on the page, or use "Forward" /
  "Back" on the right.
- **Width:** a page has twelve columns. Blocks take a quarter, a third, half,
  two thirds or the full width. On narrow screens they are stacked.
- **Preview:** the canvas shows every block with real data before you save.
- **Save:** changes only apply after "Save". "Preview" opens the page the way
  users see it.

### Public pages

At the top of the page designer, the tick **"Reachable without sign-in"** makes
a page public: anyone with the link can open it, even without an account and
without permissions for the app. Use it for registration forms, surveys or
consents from external people. The app's page list then shows "public".

What guests may and may not do:

- **Only this page.** All other pages of the app lead to the sign-in; the menu
  only shows public pages to guests.
- **Forms** on the page may be submitted: the entry is stored in the form's
  table (if "creating allowed" is on). Editing, deleting and CSV export remain
  reserved for signed-in people.
- **Script buttons** on the page may be triggered. Scripts receive
  `user = None` for guests; validate input in the script itself. JavaScript
  scripts do not work for guests.
- **Careful with data:** lists, cards, metrics, charts and queries on a public
  page show their data to everyone. The Designer warns as soon as the tick is
  set.
- The app must be published. At most 120 requests per minute and address are
  possible (`PUBLIC_RATE`).

**Input for scripts.** The block **Input field** (group "Scripts") has a name,
for example `firstname`. When someone clicks a script button on the same page,
all input fields are sent along; the script reads them as `params["firstname"]`.
The browser already checks required fields. Values from the address
(`?firstname=Ada`) pre-fill the field.

**Recognising visitors without an account.** Scripts have `session`, a small
store per visitor and app that survives page loads (session cookie, guests
included). A button script remembers, for example, `session["answer"] = new["id"]`;
the page script then shows the stored answer after a reload and hides the
inputs. This prevents duplicate entries from clicking twice. The store only
applies in this browser.

**Secret links.** For pages like "Gast" in the example app that should only work
with a specific link: create a random code with `token()` in a script, store it
on the entry, append it to the link as `?code=…` and check it on the page with
`app.table("…").first(gast_code=params["code"])`.

### Blocks

| Group | Block | Purpose |
|---|---|---|
| Content | Heading | title in three sizes, optionally with a subtitle |
| | Text | paragraph with line breaks |
| | Notice | coloured box: information, success, warning, important |
| | Image | image from an https address or from `/static/` |
| | Greeting | "Hello <name>" with date |
| Data | List | table with search, paging, create, edit, delete |
| | Cards | the same entries as cards |
| | Form | capture a new entry directly on the page |
| | CSV export | download all entries of a table |
| Evaluation | Metric | count, sum or average, optionally with a unit |
| | Progress | value relative to a target |
| | Bar chart | entries per value of a field, as a ranking |
| | Donut chart | shares of the five most frequent values, the rest as "Other" |
| | Timeline | entries per month, by a date field or the creation date |
| | Line chart | count, sum or average per day, week or month as a line, by a date field or the creation date; values on hover |
| Navigation | Button | opens a page or a link, or runs a script or Python action |
| | Page tiles | tiles for all pages of the app |
| Layout | Divider, Spacer | structure the page |
| Integration | Web request | fetches JSON from an allowed address and shows it |
| | Database query | live data from a data source, see [below](#data-from-databases-and-databricks) |
| | Tableau view | embeds a dashboard from your Tableau Server or Tableau Cloud, optionally with filters from the address (see [Tableau](#tableau)) |
| Scripts | Output | shows values, text or tables that a script sets |
| | Input field | text, email, number or long text that a script button sends along (`params["…"]`) |
| Custom blocks | see below | |

### Custom blocks

If the built-in blocks are not enough, there are two ways without programming.
Both are under **Designer → Custom blocks**; the results are available in the
page designer of all apps.

**Presets** are pre-configured standard blocks. Configure a block in the page
designer, enter a name on the right under "Reuse" and click "Save as preset".
The preset appears on the left under "Presets". Inserting it creates an
independent copy: later changes on a page do not change the preset, and vice
versa.

**HTML blocks** consist of your own HTML and settings you define yourself:

- *Settings:* one per line in the format `Label = default value`. Each line
  becomes an input field in the page designer.
- *HTML:* wherever `{{ label }}` appears, the configured value is inserted
  later. The placeholder is the label in lower case, spaces become underscores
  (`Contact Person` → `{{ contact_person }}`).
- *Always available:* `{{ nutzer }}` (signed-in person), `{{ app }}` (name of
  the app), `{{ datum }}` (today's date).

Example:

```
Settings:
  Title = Maintenance
  Text = On Friday the system is unavailable from 4 pm.

HTML:
  <div class="card">
    <h3>{{ title }}</h3>
    <p>{{ text }}</p>
  </div>
```

For security, the HTML is cleaned when saving and on every display. Common tags
are allowed (`div`, `span`, `p`, `h1`–`h4`, `strong`, `em`, `ul`, `ol`, `li`,
`a`, `img`, `table` and related) with the attributes `class`, `title`, `style`,
`href` for links, `src` and `alt` for images. Removed are scripts, event
attributes such as `onclick`, embedded foreign content (`iframe`) and addresses
that do not start with `https://`, `/`, `mailto:` or `#`. Configured values are
always inserted as text, never as HTML.

You can reuse the interface's classes, for example `card`, `btn`,
`btn-secondary`, `muted`, `small`, `badge`, `notice`.

If you need more (query data, calculate), write a block in Python, see
[Python extensions](#python-extensions).

### Publishing and sharing

In the app's settings:

- **Published:** users only see the app once this is ticked. Before that it is
  a draft and visible only to its designers.
- **Groups:** without a selection, all signed-in users may use the app. With a
  selection, only members of those groups. With Keycloak, the groups come from
  there.

### Owners and co-editors

Whoever creates an app is its **owner**. In the app's Designer, section
"Co-editors":

- The owner invites designers by user name or adds a whole group. Invited
  people need the designer permission; group members without it cannot edit the
  app.
- Co-editors may change everything in the app except the list of co-editors,
  and they may not delete the app. Only the owner and administrators
  (superusers) may.
- Other designers do not see the app in the Designer. They may use it like
  everyone else once it is published and shared with their group.
- Apps without an owner (created before this feature, or whose owner's account
  was deleted) stay open to all designers, including deleting them. Any designer
  can take such an app over with "Take over app"; afterwards others need an
  invitation.
- Administrators change the owner under `/admin/` → Apps.

### Translating an app

You build an app in one language, the source language (German). For every other
interface language (currently English) you enter translations; whoever switches
to **EN** at the top then also sees the app in English.

1. In the app's Designer, section "Translations", click **Edit translations**.
2. The page automatically lists all texts of the app: app name and description,
   tables, field labels, choices, page titles and the texts of blocks
   (headings, notices, labels, buttons). Next to each text it says where it
   occurs.
3. Enter the translation and save. Empty fields show the original text. "Only
   show missing translations" hides what is done.

Good to know:

- **Same text, same translation.** If "Status" occurs in three places, one
  translation is enough.
- **Text changed, translation gone.** If someone changes the original text, the
  translation is missing until it is entered again.
- **Data stays as it is.** A choice "Zustimmung" stays "Zustimmung" in the
  database, the API, the CSV export and in scripts; only the display and the
  form show "Consent". Filters and scripts work the same in every language.
- **Not translated** are entered data (for example the title of an event),
  texts set by scripts (`ui.set`, `message`), custom HTML blocks and the
  Designer itself. In Python scripts, `app.t("Text")` helps;
  `user["language"]` tells which language the person chose.
- **For translators without Designer access:** "Download as CSV", fill in the
  `en` column in Excel, upload it again under "Import CSV". Only filled cells for
  texts that exist in the app are taken over.
- Translations are part of versions and app exports.

### Versions

A version records the **structure** of an app: settings, tables, fields, pages
and translations. The entered data is not part of it.

- **Save:** in the app under "Versions", optionally enter a note and click
  "Save version". Versions are numbered consecutively.
- **Restore:** brings settings, fields and pages back to the saved state.
  Before that, the current state is automatically saved as a new version, so
  going back can itself be undone.
- **Data is kept:** entries are never deleted. Tables that did not exist in the
  old version remain with their data; Baukasten points this out. Fields that
  did not exist then disappear from the interface, their values stay stored.
- **Download and import:** "Download" delivers the version as a file. On the
  Designer's start page, "Create app from file" creates a new app from it, for
  example to move an app from the test to the production environment. The new
  app is a draft at first.

Versions are not created automatically with every change. Save one before you
start larger redesigns.

### Deleting an app

You delete an app in the Designer's app list ("Delete") or at the very bottom of
the app ("Delete app"). Only the owner and administrators can do this. Tables,
data, pages, versions and API keys are deleted. This cannot be undone. Download
a version first if you want to keep the structure.

### Enabling the API

In the app under "Interface (API)":

1. Tick the tables that should be reachable and click "Save shares".
2. Create a key. It is shown **only once**; copy it immediately. Without the
   tick "May write", the key can only read.
3. Give the key to the program or person who needs it.

**API documentation.** "Open API documentation" (in the app under "Interface
(API)", in your profile or under `/api-doku/`) shows a page for every app with
all addresses, all fields with their type and a Swagger interface in which every
request can be tried out directly: click "Authorize", enter the key, then "Try
it out" and "Execute" on a request. **Careful:** requests you try out act on
real data. The documentation is generated automatically from the tables and is
therefore always up to date.

The same section also shows the address of the app's [MCP server](#mcp-server-ai-agents-n8n)
for AI agents. How the API works in detail is described in [Part 3](#api).

### Data from databases and Databricks

Apps can show data from existing databases, for example PostgreSQL, SQL Server,
MySQL or a Databricks SQL warehouse. Which **data sources** exist is decided by
operations (see [Setting up data sources](#setting-up-data-sources)); in the
Designer you see them for every query under "Configured data sources". You
never get to see credentials.

**Create a query.** In the app under "Data sources", create a new query: name,
data source and SQL. Allowed is a single reading query that starts with `SELECT`
or `WITH`. "Save and test" shows the first rows of the result.

```sql
SELECT line, SUM(pieces) AS pieces, MAX(time) AS last_report
FROM plant.output
WHERE day = current_date()
GROUP BY line
```

Values that should change do not belong directly in the SQL; write them as
parameters `:name` and pass them from a script (see below).

There are two ways to use the data:

| | Show live | Mirror into a table |
|---|---|---|
| How | block "Database query" | query with "Mirror into table" |
| Freshness | on every page load, optionally automatically every 10 s to 5 min | at the configured interval, at most every minute, or at the push of a button |
| Load on the database | at most one query per cache time, no matter how many people watch | one query per sync |
| Further use | display only; in scripts with `db.saved(…)` | like any table: lists, charts, metrics, search, CSV export, API, scripts |
| Good for | current states, small results (up to 2,000 rows) | evaluations, larger amounts of data (up to 50,000 rows) |

**Show live.** In the page designer insert the block "Database query" and pick
the query. Under "Refresh automatically" (available for every block), the block
reloads regularly in the browser without reloading the page. "Cache result" on
the query decides how long a result is reused; this way 50 open browsers do not
query the database 50 times.

So that a slow data source does not slow down the app:

- The page appears immediately. The block briefly shows "Loading data …" and
  fills as soon as the result is there.
- If many people request the same query at the same time, it still goes to the
  data source only once; everyone gets the same result.
- If the data source is busy, the block waits and retries by itself.
- If the data source does not answer, the block shows the last state with a
  yellow notice instead of staying empty.
- Live queries may take at most 25 seconds (configurable by operations).
  Anything that takes longer should be mirrored.

**Mirror into a table.** On the query choose "Mirror into table" (or leave it
empty: the first sync creates a new table named after the query) and enter an
interval. The fields are created from the query's columns. With a **key
column** (for example `id`), changed rows are updated, new ones added and
vanished ones removed; entries keep their number. Without a key column, the
table is refilled on every sync. Mirrored tables are for reading: creating,
editing and deleting are switched off, because the next sync would overwrite
changes.

**Databricks.** A SQL warehouse that is asleep often needs a few minutes to
start. For live displays, a running warehouse is therefore suitable; otherwise
mirroring is the better choice: the background sync may wait up to 5 minutes.

**Rule of thumb:** mirror everything that may be minutes old. Use live only for
small results that really must be current to the second, and then with "Cache
result" of at least 30 seconds. Address tables as `catalog.schema.table`, or
operations sets catalog and schema in the data source.

### Scripts

With scripts you calculate values, fill blocks, check or complete entries and do
work in the background. They exist in **Python** (runs on the server) and
**JavaScript** (runs in the browser). They are created in the app under
"Scripts"; a test run shows output, errors with line numbers and which blocks
were filled. **Test runs work with real data.**

| Trigger | Python | JavaScript |
|---|---|---|
| When a page opens (a specific one or all) | ✓ before display | ✓ after loading |
| By button (button block, "Run script") | ✓ | ✓ without reloading the page |
| After an entry is saved | ✓ | – |
| Scheduled in the background | ✓ | – |

Rule of thumb: **Python** for data, queries with parameters, other systems or
background work. **JavaScript** when something should happen on the page
immediately at the push of a button.

**Filling blocks.** In the page designer, give the block a name under "Name for
scripts", for example `result`. A script then sets its content:

```python
open_count = app.table("requests").count(status="open")
ui.set("result", value=open_count, unit="open")
```

| Value | Applies to |
|---|---|
| `value`, `unit`, `label` | Output, Metric |
| `rows` (list of dictionaries) | Output: shown as a table |
| `text`, `title`, `subtitle` | Heading, Text, Notice, Output |
| `tone` (`info`, `success`, `warning`, `danger`) | Notice |
| `label` | Button |
| `values` (`{"field": value}`) | Form: pre-fill fields |
| `ui.hide("name")` | any block: hide |

For pure script results there is the block **Output** (group "Scripts"). It
shows a value, a text or a table, depending on what the script sets.

**After saving**, the script receives the entry as `record` and may change it;
the change is applied:

```python
if not record.get("location"):
    record["location"] = "Warehouse"
```

This applies to input via forms and via the API. What a script saves itself
does not trigger further scripts, so no loops occur.

**Scheduled** scripts run at the configured interval, for example to condense
data at night or to fetch a value from another system. This requires the
[background service](#background-work) to run.

All commands are listed in the quick reference next to the code field and in
[Part 3](#scripts-reference).

### Automations

An **automation** is the second kind of app: no pages, no users, only Python
scripts running in the background. Typical uses are syncing with other systems,
exports, checks, or a service that constantly waits for something. Unlike the
scripts of normal apps they run **real Python**: all libraries of the shared
environment (such as `requests`, `openpyxl`), files in their own working
folder, threads, runs of any length.

Only members of the group **Automatisierer** and administrators may create them
(see [Permissions](#permissions)). They get the card "New automation" on the
Designer start page. Normal users never see automations.

**When a script runs:**

| Trigger | Behaviour |
|---|---|
| Scheduled, every N minutes | slots N minutes apart. If the previous run is still working, the slot is dropped; the next run starts at the next slot after the end. Nothing is caught up. |
| Daily at a time | optionally Monday to Friday only, in Baukasten's time zone |
| Runs continuously | no time limit. If the script ends or crashes, it restarts by itself; after errors with a growing delay (10 seconds, 30 seconds, 2, 5, 10 minutes). "Switch off" stops it. |
| Manually or via webhook only | via the "Start now" button, the API or the MCP server |

A script **never runs twice at the same time**, not even when started by hand
while a scheduled run is working. Every run has a **time limit** in minutes
(default 30, at most 240), after which it is cancelled. Example: a script every
15 minutes needs 20 minutes. It runs at 10:00, the 10:15 slot is dropped (the
log records it as "skipped"), the next run starts at 10:30.

**Overview and live log.** The automation's page shows every script with its
schedule, state (running, waiting, off, error), last run and next slot, with
the buttons "Start now" and "Stop" ("Switch on" and "Switch off" for continuous
scripts). In the script editor everything the script prints with `print()`
appears in the live log after one or two seconds, together with the last 15
runs. "Save and start now" tries a change immediately. New code applies from
the next run; continuous scripts pick it up after switching off and on.

```python
import requests

response = requests.get("https://erp.example.com/api/orders",
                        headers={"Authorization": "Bearer " + secret("ERP_TOKEN")}, timeout=60)
response.raise_for_status()
new = 0
for order in response.json():
    if not app.table("orders").first(number=order["id"]):
        app.table("orders").create(number=order["id"], customer=order["customer"])
        new += 1
print(new, "new orders")
```

A continuous script is usually a loop:

```python
import time

while True:
    for file in new_files():          # your own function
        process(file)
    time.sleep(30)
```

**Tables as storage.** An automation can have tables, for example for results,
counters or "last seen". There are no pages for them; you see the data under
`/admin/` or through the API.

**Starting from outside (webhook).** With an API key of the automation that may
write:

```
curl -X POST -H "Authorization: Bearer KEY" -H "Content-Type: application/json" \
  -d '{"order": 42}' https://baukasten.example.com/api/v1/<automation>/ausloesen/<script>/
```

Response `202`: start accepted; the run begins within a few seconds. `409`: a
start is already waiting for the script, or it runs continuously. The JSON body
is available in the script as `event["daten"]` (at most 256 KB). The
automation's MCP server offers the same starts as tools `start_<script>`, plus
`automation_status` with the state of all scripts.

**Credentials** never belong in the code. Operations sets them up as a secret
(see [Background work](#background-work)); the script reads them with
`secret("NAME")`.

**Libraries.** All automations share one environment: the libraries from
`requirements.txt` and `requirements-automation.txt`. If one is missing,
operations adds it to `requirements-automation.txt` and rebuilds the image.
There are deliberately no separate installations per script.

Versions, export and import, co-editors and deleting work as for normal apps.
An exported automation can only be imported by members of "Automatisierer".

---

## 3. Developing

### Running locally

Requirement: Python 3.10 or newer.

```
python -m venv .venv
.venv\Scripts\activate            (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

$env:DEBUG=1                      (cmd: set DEBUG=1, Linux/macOS: export DEBUG=1)
python manage.py migrate
python manage.py createsuperuser
python manage.py demo             (example app "Inventar"; --neu replaces it)
python manage.py beispiel_einwilligung   (example app "Aufnahme-Einwilligung")
python manage.py runserver
```

Then open http://127.0.0.1:8000 and sign in.

Automations, scheduled scripts and mirroring of queries are handled by the
background service. When developing, start it in a second terminal:

```
python manage.py hintergrund --dauerhaft
```

With `DEBUG=1`, `python manage.py demo` additionally creates a small example
data source `demo` (file `demo-datenquelle.sqlite3`) and the page "Live-Daten"
with a Python and a JavaScript script.

Tests: `python manage.py test` (with `DEBUG=1`).

### Code structure

```
config/              settings, URLs
builder/
  models.py          App, Entity (table), Field, Record (entry), Page,
                     CustomBlock, ApiKey, AppVersion
  blocks.py          blocks: schema, data retrieval, layout validation
  forms.py           forms; RecordForm is built from a table's fields
  views.py           runtime: home page, pages, entries, CSV export, public pages
  designer.py        Designer: apps, tables, fields, pages, blocks, versions,
                     co-editors, translations
  api.py             JSON API
  mcp.py             MCP server per app
  tableau.py         Tableau embedding and Connected App tokens
  app_i18n.py        translations of app contents
  versions.py        versions: create, apply, import a state
  sanitize.py        cleaning of custom blocks' HTML
  hooks.py           extension points for Python
  services.py        web requests with host allow list
  datasources.py     external databases: connections, checks, queries, mirroring
  scripting/         scripts: python.py starts the isolated process,
                     child.py runs inside it, ops.py answers table requests,
                     triggers.py decides when scripts run
  auth.py            sign-in via Keycloak
  tours.py           texts of the tours
  locale/en/         English translation of the interface
  static/builder/    theme.css, theme.js, style.css, designer.js, tour.js,
                     transitions.js, inputs.js, home.js, font, logo
  templates/         templates
  tests.py           automated tests
extensions/          your own Python extensions
clients/python/      Python library baukasten-client for the API
docs/                this handbook (German and English)
k8s/                 Kubernetes manifests (app, migrate-job, worker, optional redis,
                     lokal/ for Docker Desktop)
gunicorn.conf.py     processes, threads and timeouts of the web server
```

Two design decisions worth knowing:

- **Entries are stored as JSON** in a shared table (`Record.data`). This way a
  table changed in the Designer needs no database migration. For very large
  amounts of data or complex queries, a regular Django model is the better
  choice.
- **A page is a list of blocks** (`Page.layout`), each with `id`, `type`,
  `width` and `props`. `blocks.clean_layout` only accepts known blocks and known
  settings from the Designer.

### Python extensions

Every Python file in the folder `extensions/` is loaded at start-up. Examples
are in `extensions/beispiel.py`. After a change the application must restart (in
Kubernetes: roll out a new image).

```python
from builder import hooks
from builder.services import http_json
```

| Decorator | Effect | Function signature |
|---|---|---|
| `@hooks.action("name", label="…")` | action triggered by a button | `(request, app)` → message text or `HttpResponse` |
| `@hooks.on_save(entity="…", app="…")` | runs after every save of an entry | `(record, created, user)` |
| `@hooks.block("name", label="…")` | custom block in the page designer | `(request, app)` → text or `format_html(...)` |
| `@hooks.api("name", methods=("GET",), write=False)` | custom API endpoint | `(request, app, data)` → dictionary or list |

`entity` and `app` in `on_save` are the short names from the address (for
example `gerate` for "Geräte") and restrict the hook; without them it applies to
everything. Errors in a hook are logged and do not abort saving.

Entries are read and written through the model:

```python
from builder.models import Record

@hooks.action("stocktaking", label="Finish stocktaking")
def stocktaking(request, app):
    devices = Record.objects.filter(entity__app=app, entity__slug="gerate")
    active = devices.filter(data__aktiv=True).count()
    return f"{active} active devices counted."
```

**Web requests** to other systems go through `http_json(url)` or
`http_request(method, url, …)` from `builder.services`. Calls only go to hosts
listed in the setting `HTTP_ALLOWED_HOSTS`; everything else is rejected. This
also applies to the block "Web request".

### API

Every app has a JSON API for the tables enabled in the Designer. The complete,
always current description of every app is available in the interface under
`/a/<app>/api-doku/` (Swagger). For tools such as Postman, Insomnia or code
generators it is available as an OpenAPI file under
`/api/v1/<app>/openapi.json`, retrievable with a key of the app.

Every request needs a key of the app:

```
Authorization: Bearer bk_…
```

| Method | Address | Effect |
|---|---|---|
| GET | `/api/v1/<app>/` | describes tables, fields and custom endpoints |
| GET | `/api/v1/<app>/<table>/` | list of entries |
| POST | `/api/v1/<app>/<table>/` | create an entry |
| GET | `/api/v1/<app>/<table>/<id>/` | read an entry |
| PUT | `/api/v1/<app>/<table>/<id>/` | replace an entry completely |
| PATCH | `/api/v1/<app>/<table>/<id>/` | change individual fields |
| DELETE | `/api/v1/<app>/<table>/<id>/` | delete an entry |
| depends on endpoint | `/api/v1/<app>/x/<name>/` | custom endpoint from `extensions` |

`<app>` and `<table>` are the short names shown in grey in the Designer.

**Querying a list.** Parameters: `page`, `page_size` (at most 200, default 50),
`q` (full-text search) and filters by field short name. Results are sorted by
`id`.

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

Dates are text in the format `YYYY-MM-DD`, references the number (`id`) of the
target entry.

**Creating an entry.** The body is a JSON object with the fields' short names.
The same checks as in the form apply.

```
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"bezeichnung": "Camera", "kategorie": "IT", "preis": 499.5}' \
  https://baukasten.example.com/api/v1/inventar/gerate/
```

**Responses.**

| Status | Meaning |
|---|---|
| 200, 201, 204 | read, created, deleted |
| 400 | invalid data; `fields` lists the errors per field |
| 401 | key missing, wrong or belonging to another app |
| 403 | key may only read, or the table does not allow the action |
| 404 | table not enabled or entry does not exist |
| 405 | method not allowed |

Errors have the form `{"error": "…"}`.

**Keys.** Only a hash is stored; the plain text cannot be read after creation.
A deleted key stops working immediately. The Designer shows when a key was last
used.

**Custom endpoint:**

```python
@hooks.api("statistics")                                  # GET /api/v1/<app>/x/statistics/
def statistics(request, app, data):
    return {"tables": {e.name: e.records.count() for e in app.entities.all()}}

@hooks.api("book", methods=("POST",), write=True)         # needs a key with write permission
def book(request, app, data):
    ...
    return {"ok": True}
```

`data` is the JSON body for POST, PUT and PATCH, and the query parameters for
GET.

### Tableau

The block **Tableau view** (group "Integration") shows a dashboard from your
Tableau Server or from Tableau Cloud directly on a page. It embeds with
Tableau's official Embedding API v3.

**In the Designer:**

1. Drag the block "Tableau view" onto the page.
2. Enter the **dashboard address** as shown in Tableau under "Share", for
   example `https://tableau.company.com/views/Plants/Overview`.
3. Optionally set title, height, toolbar (bottom, top, hidden) and "Hide tabs".
4. Optionally add **filters**, one per line in the format `Field = Value`, for
   example `Plant = Stuttgart`. With `{name}` the value comes from the page
   address: `Plant = {plant}` and the page `…/p/report/?plant=Feuerbach` shows
   the dashboard for Feuerbach. An empty value sets no filter.

The preview in the page designer does not show the dashboard; open the page
itself ("Preview") for that.

**Signing in to Tableau:** without further setup, users sign in to Tableau
themselves, on first use directly in the embedded area (with SSO usually
automatically). People only see what they may see in Tableau. More convenient is
a **Connected App** (Direct Trust): Baukasten then signs signed-in people in to
Tableau itself, with a token that is valid for 5 minutes and only suitable for
embedding. The person must exist in Tableau with the same email address (or the
same user name).

**Setup by operations:**

| Setting | Meaning |
|---|---|
| `TABLEAU_HOSTS` | allowed Tableau servers, comma-separated, e.g. `tableau.company.com`; the block does not show other addresses |
| `TABLEAU_CONNECTED_APP_CLIENT_ID`, `TABLEAU_CONNECTED_APP_SECRET_ID`, `TABLEAU_CONNECTED_APP_SECRET_VALUE` | optional: values of the Connected App from Tableau (server settings → Connected Apps → Direct Trust). Put the secret value in the Secret, not in the ConfigMap |
| `TABLEAU_USER_ATTRIBUTE` | `email` (default) or `username`: what a person is called in Tableau |

In Tableau itself, embedding must be allowed for Baukasten's address (with
Connected Apps: "Domain allowlist").

**Limits:** Tableau views are only available to signed-in people, not on public
pages. Data from Tableau does not end up in Baukasten; scripts and the API do
not see it.

### MCP server (AI agents, n8n)

Every app is also an MCP server (Model Context Protocol) at `/mcp/<app>/`. This
lets AI agents use the app's tables as tools: n8n ("MCP Client Tool" in the AI
Agent), Claude, Cursor and others.

- **Transport:** "HTTP Streamable" without streaming. Every request is a POST
  with one JSON-RPC message. There are no server-sent events.
- **Authentication:** the same key as for the API, in the header
  `Authorization: Bearer bk_…`.
- **Tools are generated automatically** from the tables enabled for the API,
  per table with the short name `<table>`:

| Tool | Effect | Only with write permission |
|---|---|---|
| `list_<table>` | search: full text `q`, filters per field, `page`, `page_size` | no |
| `get_<table>` | read one entry (`id`) | no |
| `create_<table>` | create, with the same checks as in the form | yes, and creating allowed |
| `update_<table>` | change individual fields (`id` + fields) | yes, and editing allowed |
| `delete_<table>` | delete (`id`) | yes, and deleting allowed |
| `x_<name>` | custom endpoint from `extensions` | if the endpoint writes |

Descriptions and input fields of the tools come from the table's fields (label,
type, required, choices). If someone changes a field in the Designer, the agent
sees it on the next call. For an agent that should only read, use a key without
"May write".

**Setting it up in n8n:**

1. In the app's Designer, enable tables and create a key.
2. In n8n create an "AI Agent" and add the tool "MCP Client Tool".
3. Endpoint: `https://baukasten.example.com/mcp/<app>/`.
   If n8n runs locally in Docker and Baukasten in Docker Desktop:
   `http://host.docker.internal:8080/mcp/<app>/`.
4. Server Transport: "HTTP Streamable".
5. Authentication: "Bearer Auth" with the key.
6. Tools to Include: "All" or individual tools.

To try it without n8n:

```
curl -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  https://baukasten.example.com/mcp/inventar/
```

The host under which n8n calls Baukasten must be listed in `ALLOWED_HOSTS`.

### Scripts: reference

Python and JavaScript have the same commands; in JavaScript every command that
fetches data returns a promise (write `await` in front), and fields are passed
as an object.

| Python | JavaScript | Effect |
|---|---|---|
| `app.table("t").all()` | `await app.table("t").all()` | all entries (at most 1,000) |
| `.filter(field=value)` | `.filter({field: value})` | entries with the same value |
| `.first(field=value)` / `.get(id)` | same | one entry or `None`/`null` |
| `.count(field=value)` | same | count |
| `.sum("field")` / `.avg("field")` | same | sum / average of a number field |
| `.create(field=value)` | `.create({field: value})` | create, with the same checks as in the form |
| `.update(id, field=value)` | `.update(id, {field: value})` | change individual fields |
| `.delete(id)` | same | delete |
| `db.saved("query")` | `await db.saved("query")` | result of a saved query (list of rows) |
| `db.query("source", sql, {"x": 1})` | – | free reading query with parameters `:x` |
| `http.get_json(url)` / `http.post_json(url, data)` | – | call another system (allowed hosts only) |
| `secret("NAME")` | – | [automations](#automations) only: read the secret `SCRIPT_SECRET_NAME` |
| `ui.set("name", …)` / `ui.hide("name")` | `ui.set("name", {…})` / `ui.hide("name")` | fill or hide a block |
| `message("Text")` | `message("Text")` | message for the person who triggered the script |
| `token()` / `token(32)` | – | random, unguessable code, e.g. for secret links |
| `session["key"]` | – | small store per visitor (browser) and app that survives page loads; guests included. At most 4 KB, only plain values (text, numbers, lists, dictionaries) |
| `print(…)` | `console.log(…)` | output in the log or test run |
| `app.name`, `app.slug` | – | name and short name of the app, e.g. for links (`"/a/" + app.slug + "/p/page/"`) |
| `app.t("Text")` | – | text in the person's language from the app's [translations](#translating-an-app), otherwise unchanged |
| `user` | `user` | signed-in person: `name`, `username`, `email`, `groups`, `language` (e.g. `"de"`, `"en"`; scheduled or guests: `None`) |
| `event`, `params` | `event`, `params` | trigger and address parameters (`?line=3` → `params["line"]`); button scripts get the parameters of the page the button is on, plus the page's input fields |
| `record` | – | the saved entry (only "after saving") |

Entries are dictionaries with `id`, the fields' short names, `created_at` and
`updated_at`.

**What Python scripts may do.** Python scripts run in their own process with
[RestrictedPython](https://restrictedpython.readthedocs.io/). Allowed are the
usual language features, your own functions and classes and the modules `math`,
`statistics`, `datetime`, `json`, `re`, `random`, `string`, `decimal`,
`collections`, `itertools`, `functools` and `time`. Not allowed are files, other
modules, `eval`/`exec` and names starting with `_`. Data can only be accessed
through the commands above, and only in the script's own app. A run may take at
most 10 seconds, use 512 MB of memory and issue 1,000 commands (configurable,
see [Configuration](#configuration)).

**What JavaScript scripts may do.** JavaScript runs in the browser of the person
who opens the page, with their permissions: what they may not do in the
interface, their script may not do either. The code runs isolated (sandbox
iframe with its own worker): it sees neither the page nor cookies and cannot
open network connections. Free SQL queries and web requests are therefore only
available in Python. The code is readable in the browser by everyone who opens
the page: do not put passwords or keys in it.

**Errors.** An error only aborts the script, never the page. Designers of the
app see it on the page with the line number and a link to the script; other
users do not. The last 20 runs are listed in the editor; for page loads only
failed runs are logged.

### Python library (baukasten-client)

For programs outside Baukasten, such as evaluations in Jupyter, Excel imports or
other services, there is a Python library without further dependencies. It
talks to the [API](#api) and has the same commands as scripts, so code can be
moved between both.

```
pip install ./clients/python
```

```python
from baukasten_client import Client, BaukastenError

bk = Client("https://baukasten.example.com", app="inventar", key="bk_…")
devices = bk.table("gerate")

print(devices.count(kategorie="IT"))
for d in devices.iter(aktiv=True):          # loads page by page
    print(d["bezeichnung"], d["preis"])

new = devices.create(bezeichnung="Camera", kategorie="IT", preis=499.5)
devices.update(new["id"], standort="Warehouse")

try:
    devices.create(kategorie="Unknown")
except BaukastenError as e:
    print(e.status, e.fields)               # 400 and the errors per field
```

More commands: `bk.describe()` (tables and fields), `.replace(id, data)`
(replace an entry completely), `bk.call("name", …)` (custom endpoint). For a
server with a certificate from an internal certificate authority:
`Client(…, cafile="company-ca.pem")`. Details are in `clients/python/README.md`.

### Adding a block to the core

A new standard block consists of three parts:

1. `register(...)` in `builder/blocks.py`: name, settings, group and a
   `prep_…` function that delivers the data for display.
2. A branch in `builder/templates/builder/block.html`.
3. Optionally an icon in `ICONS` in `static/builder/designer.js`.

The test `test_every_block_type_renders` automatically checks that every
registered block renders without errors.

### Maintaining translations

German is the source language in the code. Texts are marked with `gettext`
(Python), `{% translate %}` (templates) and `gettext()` (JavaScript). After text
changes, in the folder `builder/`:

```
django-admin makemessages -l en -d django
django-admin makemessages -l en -d djangojs --ignore "static/builder/swagger/*"
(enter translations in locale/en/LC_MESSAGES/*.po)
django-admin compilemessages
```

This requires GNU gettext. The compiled `.mo` files are in the repository; the
container does not need gettext. Another language is added via `LANGUAGES` in
`config/settings.py` and a new folder under `locale/`; the language switch in
`templates/builder/_language.html` then needs another button. The handbook has
one file per language in `docs/` (`HANDBUCH.md`, `HANDBOOK.en.md`); the help page
shows the one matching the interface language.

---

## 4. Operating

### Configuration

Everything environment-specific comes from environment variables.

| Variable | Meaning |
|---|---|
| `SECRET_KEY` | long random value; required as soon as `DEBUG` is not set |
| `DATABASE_URL` | e.g. `postgres://user:pass@host:5432/baukasten`; SQLite if not set |
| `ALLOWED_HOSTS` | host names of the application, comma-separated |
| `CSRF_TRUSTED_ORIGINS` | e.g. `https://baukasten.example.com` |
| `HTTP_ALLOWED_HOSTS` | hosts that web requests may reach, comma-separated |
| `HTTP_TIMEOUT` | timeout for web requests in seconds, default 10 |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET` | sign-in via Keycloak, see below |
| `OIDC_ONLY` | `1` hides the local sign-in |
| `OIDC_GROUPS_CLAIM` | name of the claim with the groups, default `groups` |
| `OIDC_DESIGNER_ROLE` | role for the Designer, default `baukasten-designer` |
| `DATASOURCE_<NAME>` | a data source, see [Setting up data sources](#setting-up-data-sources) |
| `SCRIPT_TIMEOUT` | timeout for Python scripts in seconds, default 10 |
| `SCRIPT_MEMORY_MB` | memory limit per Python script (Linux only), default 512 |
| `SCRIPT_MAX_CALLS` | commands per script run, default 1000 |
| `AUTOMATION_PARALLEL` | simultaneous runs of automations (continuous scripts do not count), default 4 |
| `AUTOMATION_MEMORY_MB` | memory limit per automation run (Linux only), default 2048, 1024 in the manifest |
| `AUTOMATION_MAX_TIMEOUT_MINUTES` | longest time limit a script may set, default 240 |
| `AUTOMATION_MAX_CALLS` | commands (`app.table`, `db`, `secret`) per run, default 0 = unlimited |
| `SCRIPT_SECRET_<NAME>` | secret for automations, `secret("NAME")` in the script; set only in the background service |
| `REDIS_PASSWORD` | password for the Redis from `k8s/redis.yaml` |
| `PUBLIC_RATE` | guest requests on public pages per address and minute, default 120, 0 = no limit |
| `TABLEAU_HOSTS`, `TABLEAU_CONNECTED_APP_*`, `TABLEAU_USER_ATTRIBUTE` | embedding Tableau, see [Tableau](#tableau) |
| `DEFAULT_USER_GROUPS` | groups every person automatically belongs to, default `Viewer` |
| `REDIS_URL` | shared cache in Redis; empty = table in PostgreSQL, see [Scaling](#scaling-and-load) |
| `GUNICORN_WORKERS`, `GUNICORN_THREADS`, `GUNICORN_TIMEOUT` | processes and threads per pod, default 3, 4 and 60 s |
| `DB_CONN_MAX_AGE` | how long database connections stay open, default 60 s |
| `QUERY_TIMEOUT` | timeout for queries a page waits for, default 25 s |
| `SYNC_TIMEOUT` | timeout for mirroring in the background, default 300 s |
| `QUERY_PARALLEL` | simultaneous queries per data source in the whole cluster, default 4 |
| `QUERY_PARALLEL_<NAME>` | the same for a single source, e.g. `QUERY_PARALLEL_DWH=2` |
| `QUERY_WAIT` | seconds a request waits for a free slot, default 2 |
| `LAZY_QUERIES` | `false` loads query blocks directly with the page instead of afterwards |
| `LOG_LEVEL` | default `INFO` |
| `DEBUG` | `1` only locally |

### Local Kubernetes (Docker Desktop)

To try the Kubernetes installation on your own computer:

1. In Docker Desktop under "Kubernetes", create a cluster of type **Kubeadm**
   (one node, uses locally built images directly).
2. In the Baukasten folder run:
   ```
   powershell -ExecutionPolicy Bypass -File k8s\lokal\deploy.ps1 -OhneBeispiele
   ```
3. Open http://localhost:8080 and sign in as `admin`. The password is in
   `k8s\lokal\geheim.env` (`ADMIN_PASSWORD`).

The script builds the image, creates random credentials on the first run, starts
PostgreSQL in the cluster, migrates, rolls out and creates the admin account.
Without `-OhneBeispiele` it also tries to create the example apps; the inventory
demo cannot write its example data source in the cluster, so the script stops
at the end. Create the consent example app afterwards with:

```
kubectl -n baukasten exec deploy/baukasten -- python manage.py beispiel_einwilligung
```

For an update, run the same script again. It uses the same manifests as
production; what is different locally (no TLS, service on localhost:8080, no
registry, `host.docker.internal` allowed for containers such as n8n) is in
`k8s/lokal/kustomization.yaml`. Log of the last run: `k8s\lokal\letzter-lauf.log`.
Remove everything: `kubectl delete namespace baukasten`.

If Docker Desktop restarts repeatedly, the WSL virtual machine usually has too
little or too much memory: give it enough for Kubernetes (`memory=` in
`%USERPROFILE%\.wslconfig`), but leave enough for Windows.

### Kubernetes

The application is stateless: sessions and data are in the database. Several
replicas run without sticky sessions.

```
docker build -t registry.example.com/baukasten:1.0.0 .
docker push registry.example.com/baukasten:1.0.0

kubectl apply -f k8s/secret.yaml          (create from secret.example.yaml)
kubectl apply -f k8s/migrate-job.yaml     (creates or updates tables)
kubectl apply -f k8s/app.yaml
kubectl apply -f k8s/worker.yaml          (background service, see below)
kubectl exec deploy/baukasten -- python manage.py createsuperuser
```

First adjust image, host name and ingress class in the manifests. For every new
version, roll out the migration job first, then the deployment. `/healthz`
answers the probes. TLS and the redirect from http to https are handled by the
ingress.

### Scaling and load

**Principle:** all apps run together in the same pods; an app is data, not a
separate service. How many pods run depends on the total load, not on the
number of apps. The state lives entirely in PostgreSQL and the cache, so every
pod can answer every request.

**Concurrent requests.** gunicorn runs with threads (`gunicorn.conf.py`):
`GUNICORN_WORKERS × GUNICORN_THREADS` concurrent requests per pod, default
3 × 4 = 12. More pods are added automatically by the HorizontalPodAutoscaler in
`k8s/app.yaml` (2 to 6 pods at 70 % CPU). Updates roll out without downtime
(new pod first, then the old one goes), and during node maintenance one pod
always stays reachable.

**Count database connections.** Every thread holds a connection to PostgreSQL.
Roughly: at most pods × workers × threads + 5 for the background. With the
defaults and 6 pods that is 6 × 3 × 4 + 5 = 77; PostgreSQL allows 100 by
default. If you configure more pods or threads, increase `max_connections` or
put a connection pool such as PgBouncer in front.

**Cache.** Without further settings it lives in a table of the application's
own database (`baukasten_cache`, created by the migration job). That is enough
to start and needs no additional service. With many pods and many live queries,
Redis is faster: apply `k8s/redis.yaml` or use an existing Redis and set
`REDIS_URL` in the Secret. The cache is only a cache; if it fails, no data is
lost.

**External data sources under load.** Three protective mechanisms make sure a
slow source (typically Databricks) does not slow down the whole of Baukasten:

| Mechanism | Effect | Setting |
|---|---|---|
| Lazy loading | pages appear immediately; query blocks load afterwards. A block that would have to wait does not occupy a thread; the browser asks again after 2 seconds. | `LAZY_QUERIES` |
| Shared result | the same query runs only once at a time in the whole cluster; everyone else gets its result or the last state. On errors the last state is shown for up to 24 hours. | "Cache result" per query |
| Limit per source | at most this many simultaneous queries per source, across all pods. Whoever gets no slot receives "busy" instead of waiting. | `QUERY_PARALLEL`, `QUERY_PARALLEL_<NAME>`, `QUERY_WAIT` |
| Timeouts | pages wait at most `QUERY_TIMEOUT` (25 s). Mirroring in the background may take `SYNC_TIMEOUT` (300 s). | `QUERY_TIMEOUT`, `SYNC_TIMEOUT` |

`GUNICORN_TIMEOUT` must be above `QUERY_TIMEOUT`. `QUERY_PARALLEL` depends on
what the source can handle: for a small Databricks warehouse 2 to 4 make sense,
for a PostgreSQL replica rather 10.

**Measured** with one pod (2 workers × 4 threads), cache in PostgreSQL and a
data source whose queries take 3 seconds each, limit 2 at a time: 40 people
open 10 different live pages at the same time.

| | without last state in the cache | with last state |
|---|---|---|
| page visible | after 0.2 s | after 0.2 s |
| data there | median 17 s, at the latest 32 s | median 0.4 s, at the latest 3.4 s |
| another page in between | median 16 ms, 95 % under 25 ms | median 18 ms, 95 % under 40 ms |
| simultaneous queries at the source | at most 2 | at most 2 |

Without cache it takes longer because the source deliberately only gets 2
queries at a time (10 × 3 s ÷ 2 = at least 15 s). What matters: the rest of
Baukasten stays fast, and the source is never overloaded.

**When a separate installation?** If an app must be strictly separated from the
others (business-critical, very high load, special data rules), it gets its own
Baukasten deployment with its own database: the same image, installed twice.
For everything else, the shared installation is simpler and cheaper.

### Setting up data sources

Every data source is an environment variable `DATASOURCE_<NAME>` with a
connection address. The part after `DATASOURCE_` becomes, in lower case, the
name designers choose. The addresses contain credentials and therefore belong
in the Kubernetes Secret (`k8s/secret.example.yaml`).

```
DATASOURCE_STOCK=postgresql://reader:PASSWORD@db.example.com:5432/stock
DATASOURCE_DWH=databricks://token:dapi…@adb-123.azuredatabricks.net/sql/1.0/warehouses/abc?catalog=main&schema=plant
DATASOURCE_LEGACY=mssql://reader:PASSWORD@sql.example.com:1433/legacy?driver=ODBC+Driver+18+for+SQL+Server
DATASOURCE_SHOP=mysql://reader:PASSWORD@mysql.example.com:3306/shop
```

Special characters in passwords or tokens must be URL-encoded (`/` as `%2F`,
`@` as `%40`).

| Kind | Driver | Note |
|---|---|---|
| PostgreSQL | `psycopg`, included | the session is opened read-only |
| Databricks | `databricks-sql-connector`, included | server host name and HTTP path from the SQL warehouse's connection details; token of a service principal with read permissions; additional timeout limit with `&timeout=seconds` |
| SQL Server | `pyodbc` plus ODBC driver 18, **not included** | install in the Dockerfile; connection with `ApplicationIntent=ReadOnly` |
| MySQL | `pymysql`, **not included** | `pip install pymysql` |

**Important:** Baukasten only accepts queries that start with `SELECT` or `WITH`
and rejects modifying statements. This check is a safeguard, not a replacement
for permissions: create a database user for every data source that may **only
read**, and only the tables that are needed. Every query has a timeout: 25
seconds for pages (`QUERY_TIMEOUT`), 300 seconds for mirroring
(`SYNC_TIMEOUT`); for Databricks, `&timeout=` in the address limits it
additionally. Live results are limited to 2,000 rows, mirrored ones to 50,000.

All designers can use all data sources. The results of saved queries can be seen
by everyone who may use the app.

### Background work

The **background service** `python manage.py hintergrund --dauerhaft` starts,
watches and stops the scripts of [automations](#automations). Every 30 seconds
it also handles the scheduled scripts of normal apps and the mirroring of
queries. In Kubernetes this is the deployment `baukasten-worker` from
`k8s/worker.yaml`: exactly one pod that runs permanently and replaces the
former CronJob (when switching: `kubectl delete cronjob baukasten-hintergrund`).
Without `--dauerhaft` the command handles the work of normal apps once, no
automations.

How the service works:

- Every run is its own process. Up to `AUTOMATION_PARALLEL` runs work at the
  same time, continuous scripts on top. The pod therefore needs memory for these
  runs; the manifest's limit is 4 GiB.
- A lock in the database with a heartbeat every two seconds makes sure a script
  never runs twice. If the pod dies hard, the next service frees the locks after
  90 seconds and records the run as "aborted".
- On shutdown (deploy, restart) running scripts get SIGTERM and have ten
  seconds to clean up. They then count as "aborted"; continuous scripts restart
  right away with the new pod, scheduled scripts at their next slot.
- A heartbeat file serves the `livenessProbe`: if the service hangs, Kubernetes
  restarts it.

**Secrets for scripts** live in the secret `baukasten-skript-geheimnisse`
(template in `k8s/secret.example.yaml`, locally `k8s\lokal\skript-geheim.env`),
one entry `SCRIPT_SECRET_<NAME>` each. Only the worker pod gets this secret.
All automations see all entries; only put credentials there that automators
may use.

**Libraries** for automations are listed in `requirements-automation.txt` and
are baked into the image (one environment for all).

Errors are in the pod's log and in the app (for scripts under "Last runs", for
queries under "Last sync").

### Sign-in via Keycloak

Without `OIDC_` variables, users sign in with local accounts (managed under
`/admin/`). With the variables, the sign-in page shows "Sign in with company
account".

In Keycloak:

1. Create a client of type "OpenID Connect" with client authentication.
2. Valid redirect URI: `https://<host>/oidc/callback/`. Post-logout redirect:
   `https://<host>/`.
3. Give the client a mapper "Group Membership" named `groups` and switch on
   "Add to userinfo" so that groups arrive.
4. Create the role `baukasten-designer` and assign it to the people who build
   apps.

In Baukasten: `OIDC_ISSUER` is the address of the realm, for example
`https://keycloak.example.com/realms/company`. Client ID and secret come from
the client.

On the first login the user is created. Name, email, groups and the designer
role are taken from Keycloak on **every** login; whoever loses the role there
also loses it here on the next login. A local account with a password is never
taken over by a Keycloak account of the same name.

### Permissions

| Who | May |
|---|---|
| Users | use published apps that are shared with everyone or with one of their groups; public pages need no sign-in at all |
| Designers | edit their own apps and apps they were invited to; create new apps and custom blocks |
| Automators | additionally create and edit [automations](#automations) (real Python in the background) |
| Administrators (superusers) | additionally all apps in the Designer and `/admin/`: users, groups, all data |

A designer is whoever has the designer role in Keycloak, or locally the
permission "May edit apps in the Designer" or staff status. Staff accounts also
see the link "Admin" in the header.

An automator is whoever belongs to the group **Automatisierer** (the update
creates it with both permissions; an administrator adds members under
`/admin/` → Groups, with Keycloak a group of the same name). Staff status alone
is not enough, because automations run arbitrary code on the server. Only
automators can be invited as co-editors of an automation.

**Owners and co-editors.** Whoever creates an app is its owner and can invite
co-editors; details in [Owners and co-editors](#owners-and-co-editors).

**Default groups.** Every person automatically belongs to the group **Viewer**:
when created, on every sign-in and when synchronised with Keycloak. Existing
users were added during the update. Which groups these are is set by
`DEFAULT_USER_GROUPS` (comma-separated, empty = none). What the group may do is
determined by its permissions under `/admin/` → Groups. An app restricted to
"Viewer" is therefore open to all signed-in people.

A group's view permissions ("Can view …") only apply in the administration under
`/admin/`, which only people with staff status can reach. Do not give a default
group permissions for users and sessions there, otherwise every person with
staff status sees other people's data.

### Administration (/admin/)

The administration is organised by app:

- **Home page:** at the top a table of all apps with the number of tables,
  entries, pages and scripts, and "View data".
- **View data:** shows every table of an app with real columns, 50 entries per
  page, newest first. A click on the number opens the entry.
- **Opening an app** shows its tables (with a link to the entries), pages,
  scripts, queries, API keys, versions, owner and co-editors on one page.
- **Lists** (entries, fields, scripts, script runs, queries, keys, versions) can
  be filtered by **app** on the right, entries additionally by table. The search
  for entries searches the whole content.
- **An entry** shows its fields readably at the top and below the content as
  JSON for editing.

Apps, tables, fields and pages are better built in the Designer: input is
checked there and pages stay consistent. The administration is meant for the
overview, for corrections, and for users and groups.

### Company logo and design

- **Logo:** put the official logo file as `logo.svg` or `logo.png` into
  `builder/static/builder/brand/`. It appears in the header to the right of
  "Baukasten", separated by a vertical line, and on the sign-in page on a white
  background. Notes are in the file `LIESMICH.txt` in this folder. No logo is
  included on purpose: use the original file from your brand portal and follow
  its rules. Logo files are excluded from Git via `.gitignore` so they do not
  end up in a public repository.
- **Colours, font, rounding:** defined as variables in
  `builder/static/builder/theme.css`. A company stylesheet can be included in
  `templates/base.html` after `theme.css`. The colours for dark mode are in the
  same file in the block `html[data-theme="dark"]` (and again for "automatic" in
  `@media (prefers-color-scheme: dark)`); if you change colours, change both
  versions.
- **Font:** IBM Plex Sans is included locally (SIL Open Font License). Nothing
  is loaded from the internet.

After changes to static files the image must be rebuilt (`collectstatic` runs in
the Dockerfile).

### Security

- **Sign-in** is required for all pages, except pages a designer explicitly
  made public. The API and the MCP server require a key.
- **Permissions** are checked on the server: access to apps, designer
  permission per app (owner, co-editors), creating/editing/deleting per table,
  write permission of the API key, and for guests only the forms and script
  buttons of public pages.
- **Input** is escaped automatically in templates. The HTML of custom blocks is
  cleaned (see above). The CSV export defuses cells that Excel would execute as
  formulas.
- **Web requests** only go to allowed hosts (`HTTP_ALLOWED_HOSTS`), so internal
  addresses cannot be queried through the Designer. Tableau dashboards are only
  embedded from `TABLEAU_HOSTS`.
- **API keys** are only stored as a hash.
- **Python extensions** run with all permissions of the application. Only
  reviewed code belongs in the folder `extensions/`.
- **Python scripts from the Designer**, on the other hand, run isolated: own
  process without environment variables (so without passwords, keys and
  database access), RestrictedPython, time limits and on Linux memory and file
  limits. They reach data only through Baukasten's commands and only in their
  app. Residual risk: a bug in RestrictedPython could allow a script more. If you
  must protect against that, run scripts in a separate container without network
  access; this is not built in yet.
- **Automations** run real Python; whoever may build them can run arbitrary
  code in the worker pod. Hence only the group "Automatisierer". It is still
  hardened: scripts only run in the worker pod, never in the web pod; they start
  without environment variables; on Linux the service makes itself
  "non-dumpable" (`PR_SET_DUMPABLE`) so a script cannot read its credentials
  through `/proc`; the pod has no Kubernetes token; if it runs as root, scripts
  run as `nobody`. Scripts reach tables only through Baukasten's commands and
  only in their own app. **Not isolated** is the network: scripts reach
  everything the pod reaches. Redis therefore requires a password; NetworkPolicies
  can restrict the worker further.
- **JavaScript scripts** run in the browser in a sandbox without access to the
  page, cookies and the network, with the permissions of the respective person.
- **Data sources:** credentials only in environment variables or Secrets; they
  never appear in the interface and are removed from error messages. Read-only
  users in the database are mandatory.
- **Public pages** are limited to `PUBLIC_RATE` requests per address and minute.
- **Not included:** a rate limit for the API (set it up at the ingress) and an
  audit log of who changed what when.

### Backup

All content is in the database: apps, data, versions, users. A regular database
backup is enough. Versions do not replace it, because they contain no data.

---

## Frequently asked questions

**I don't see an app that should exist.**
Either it is not published yet, or it is restricted to groups you are not in.
Your profile shows your groups; whoever built the app sees under "Settings and
sharing" who it is shared with.

**I don't see the link "Designer".**
You lack the designer permission. With a company account, Keycloak grants it via
the role `baukasten-designer`, otherwise the administration does.

**I can't find an app in the Designer.**
It belongs to someone else. Ask its owner to add you as a co-editor.

**I accidentally broke something on a page.**
If a version was saved: restore it in the app under "Versions". No data is lost.
Without a version the structure cannot be recovered; so save a version before
larger redesigns.

**A block shows a red-bordered notice.**
It is missing a setting, usually the table or the field, or the table was
deleted. Click it in the page designer and fill it in on the right.

**A script reports an error.**
Designers of the app see the error on the page with the line number and a link.
In the editor, "Save and test" shows output and errors; "Last runs" and your
profile list earlier errors. Other users do not see script errors, only that the
block stays empty.

**The live data from Databricks loads very slowly.**
The SQL warehouse is probably asleep and must start first. For live displays use
a running warehouse or mirror the query into a table.

**A query block shows "loading" or "busy".**
The data source is currently receiving as many queries as operations allows. The
block retries by itself. If this happens often: increase "Cache result", mirror
the query or ask operations to adjust `QUERY_PARALLEL` for this source.

**A Tableau view stays empty.**
Check that you are signed in to Tableau (or that the Connected App is set up),
that the server is listed in `TABLEAU_HOSTS` and that Tableau allows embedding
for Baukasten's address. The link below the block opens the dashboard directly
in Tableau.

**My API call returns 401.**
The key is missing, wrong or belongs to another app. It must be in the header
`Authorization: Bearer bk_…`. With **403** the key may only read or the table
does not allow the action, with **404** the table is not enabled.

**I didn't copy my API key.**
It cannot be shown again. Delete it (in your profile or in the app) and create a
new one.

**How do I get data into Excel?**
Once: put the block "CSV export" on a page and download. Regularly: Power Query
in Excel with the API, or the Python library.

**Where do I see all data of an app at a glance?**
As an administrator under `/admin/` → "View data" for the app.

**How do I switch the handbook to German?**
Select **DE** in the language switch in the top right. The choice is remembered.

## Current limitations

- **Tested** with SQLite: 194 automated tests and runs in the browser (Chrome),
  including Python and JavaScript scripts, live display and mirroring with a
  SQLite data source, and the Python library against a real server. With
  PostgreSQL (for Baukasten and as a data source) and gunicorn as in the
  container, the load test from [Scaling](#scaling-and-load) ran, once with the
  cache in PostgreSQL and once with Redis. The Docker build and the local
  manifests run on Kubernetes in Docker Desktop with PostgreSQL 16. Tableau
  embedding was tested with Tableau Public. **Not tested:** a real production
  cluster (ingress, TLS), the complete sign-in against a real Keycloak, a
  Tableau Connected App, and connections to real databases other than SQLite and
  PostgreSQL. For Databricks only the way the address is passed to the driver
  and the way errors arrive have been checked; a connection to a real warehouse
  is missing.
- **Scripts:** every Python run starts its own process (about 0.1 to 0.3
  seconds). Scripts on page load make the page correspondingly slower.
  JavaScript scripts need a current browser.
- **Automations:** schedules are accurate to a few seconds. There is one worker
  pod; all scripts share its CPU and memory and one library environment (no
  packages of their own per script). Secrets apply to all automations. Errors
  send no e-mail, they are only shown in the Designer. The pod's network is not
  restricted. On Windows (development) there is no memory limit, and "Stop" ends
  the process immediately without cleanup.
- **Data sources:** set up by operations through environment variables, not in
  the Designer; all designers can use all sources. Mirrored tables do not
  trigger "after saving" scripts.
- **Permissions** apply per app and per table, not per page, entry or field
  (public pages are the exception). Whoever may use an app sees all its pages.
  In the Designer there is only "may edit the whole app", no permissions per
  page or script. Custom blocks and presets apply to all designers.
- **Concurrent editing:** if two co-editors save the same page or the same
  script, the last saved version wins, without a warning.
- **Versions** are only created at the push of a button and contain no data.
  Tables are never deleted when restoring.
- **API:** no rate limit, no sorting other than by `id`, filters only on
  equality.
- **Tour:** whether someone has seen it is remembered by the browser, not by the
  server.
- **Translation:** interface and handbook in German and English; app contents
  can be translated (see [Translating an app](#translating-an-app)). The
  placeholders `nutzer`, `app`, `datum` in custom blocks are single-language.
  Some newer interface texts (translations, co-editors, public pages, MCP and
  Tableau settings in the Designer) are still only in German.
- **Accessibility:** keyboard operation and labels are taken into account; a
  check against a standard (e.g. WCAG) has not taken place. Dragging in the page
  designer requires a mouse; as an alternative there is clicking and "Forward" /
  "Back".

## Glossary

| Term | Meaning |
|---|---|
| App | an application in Baukasten, consisting of tables and pages |
| Table | one kind of entry, for example "Devices" |
| Field | one piece of information per entry, for example "Price" |
| Entry | one record in a table |
| Page | what users see; consists of blocks |
| Public page | a page reachable without sign-in |
| Block | an element of a page, for example a list or a metric |
| Preset | a pre-configured block for reuse |
| Short name | technical name in addresses, API and code, for example `gerate` |
| Version | saved structure of an app, without data |
| Designer | area for building apps; also the role of the people allowed to do so |
| Owner, co-editor | the person who created an app and the designers invited to edit it |
| Default group | group every person automatically belongs to (Viewer) |
| OpenAPI, Swagger | standard for API descriptions and the interface that displays them and lets you try them out |
| MCP | Model Context Protocol: the standard through which AI agents use the app's tables as tools |
| Administration | the area under `/admin/` for users, groups and the overview of all data |
| Data source | an external database set up by operations, e.g. a Databricks SQL warehouse |
| Query | saved SQL against a data source, shown live or mirrored |
| Mirroring | regularly copying a query's result into a table |
| Script | Python or JavaScript code that runs on a trigger |
| Translation | the English version of an app's texts, maintained in the Designer |
