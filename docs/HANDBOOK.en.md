# Baukasten - Handbook

Baukasten is a tool for creating internal web apps in the browser: define data,
assemble pages from building blocks, and publish them. Developers can add
Python logic. Technically, Baukasten is a Django application that runs on
Kubernetes.

This handbook is also available in the application under **Help**. Use the
language switch in the top-right corner to change between German and English.

## Where to start

| You want to ... | Read |
|---|---|
| use an existing app | [1. Using apps](#1-using-apps) |
| build your first app | [Quick start](#quick-start-your-first-app-in-15-minutes), then [2. Building apps](#2-building-apps) |
| display data from a database or Databricks | [External data sources](#external-data-sources) |
| access data from another program | [API](#api) and the API documentation in the application |
| write logic | [Scripts](#scripts) and [3. Developing](#3-developing) |
| run Baukasten locally in Kubernetes | [Kubernetes](#kubernetes) |
| install or operate Baukasten | [4. Operating](#4-operating) |
| find a quick answer | [Frequently asked questions](#frequently-asked-questions) |

## The basic concepts

```
Baukasten
└── App                  an application for one purpose
    ├── Tables           the available data
    │   └── Fields       the properties of each entry
    │       └── Entries  the actual data
    ├── Pages            what users see
    │   └── Blocks       lists, charts, forms, and more
    ├── Scripts          Python or JavaScript logic
    ├── Queries          SQL against external databases
    ├── API keys         access for other programs
    └── Versions         saved states of the app configuration
```

## Quick start: your first app in 15 minutes

1. Sign in and open the **Designer**.
2. Create an app and give it a name.
3. Add a table and define its fields. A table should contain the data that
   belongs together; use a reference field to connect it to another table.
4. Create a page and add blocks such as a table, form, metric, or chart.
5. Preview the page, then publish the app and grant access to the required
   users or groups.

## 1. Using apps

### Sign in

Sign in with the local account or the configured Keycloak provider. The
language is selected automatically from your browser on the first visit and
can be changed at any time using **DE** or **EN** in the top bar.

### Home page and app pages

The home page lists the apps available to you. Open an app to use its pages,
forms, filters, exports, and actions. The app navigation shows only pages that
are published in the navigation.

### Theme, navigation, and profile

Use the theme switch to choose light or dark mode. On narrow screens the
navigation is available from the menu button. Your profile contains your
account information and, where permitted, your API keys.

## 2. Building apps

### Three steps to an app

1. Define tables and fields.
2. Design pages from blocks.
3. Publish the app and grant access.

### Tables and fields

A table is a collection of entries. Fields define the type and validation of
each value. Use short, stable field names for API clients. Choice fields have
one value per line; reference fields connect entries from different tables.

### Page designer and blocks

The page designer arranges blocks on a page. Available blocks include tables,
forms, metrics, charts, line charts, images, links, exports, and web requests. Configure
each block in the designer and use the preview before publishing.

### Scripts

Scripts can run when a page opens, after an entry is saved, from a button, or
on a schedule. Python scripts run on the server; JavaScript scripts run in the
browser. Keep secrets in API keys or environment configuration, never in page
content.

### Publishing, access, and versions

An unpublished app is not available to normal users. Access can be granted to
groups, and designers can be added separately. Save versions before larger
changes so that a previous configuration can be restored.

### Translating an app

An app is built in one language, the source language (German). For every other
UI language (currently English) you can add translations; people who switch to
**EN** then see the app in English as well.

1. In the Designer of the app, section **Translations**, click **Edit
   translations**.
2. The page lists all texts of the app automatically: app name and
   description, tables, field labels, choices, page titles, and block texts
   (headings, notices, labels, buttons), each with where it occurs.
3. Enter the translations and save. Empty fields show the original text.

Notes:

- The same text is translated once, wherever it occurs. If someone changes the
  original text, its translation is missing until it is entered again.
- Stored data does not change: a choice "Zustimmung" stays "Zustimmung" in the
  database, the API, CSV exports, and scripts; only display and forms show
  "Consent".
- Not translated: entered data, texts set by scripts (`ui.set`, `message`),
  custom HTML blocks, and the Designer itself. Python scripts can use
  `app.t("Text")` and `user["language"]`.
- For translators without Designer access: download the CSV, fill in the `en`
  column in Excel, and upload it under **Import CSV**.
- Translations are part of versions and app exports.

### Co-editors

Whoever creates an app becomes its **owner**. In the Designer, the section
**Co-editors** of an app lists who else may edit it:

- The owner invites designers by user name or adds a whole group. Invited
  people need the designer permission; group members without it cannot edit.
- Co-editors can change everything in the app except its co-editors, and they
  cannot delete the app. Only the owner and administrators (superusers) can.
- Other designers do not see the app in the Designer. They can use it like any
  user once it is published and their group has access.
- Apps without an owner (created before this feature, or whose owner's account
  was deleted) stay open to all designers, including deleting them. Any
  designer can take one over with
  **Take over app**; afterwards others need an invitation.
- Administrators can transfer ownership under `/admin/` → Apps.

### Example app: recording consent

`python manage.py beispiel_einwilligung` creates an app in which organisers add
an event and participants agree to or decline photo, video, or audio
recordings. Signed-in participants use the participation link; guests without
an account use the **guest link** `/a/einwilligung/p/gast/?code=<code>`. It is
built only with Baukasten features: a save script creates the secret code with
`token()`, the page "Gast" is a public page with two input fields and two
script buttons, and the scripts store the answer with origin "Gast" and keep
its number in `session`. After a reload guests see their decision, and clicking
again changes the answer instead of creating a second one. Nobody verifies the
name; in another browser a guest counts as a new person.

### Public pages

In the page designer, **Reachable without sign-in** makes a page public: anyone
with the link can open it without an account or app permissions. Guests can
only use this page, submit its forms (into the form's table, if creating is
allowed), and trigger its script buttons; scripts receive `user = None` for
them. Lists, cards, metrics, charts, and queries on a public page show their
data to everyone, so the Designer shows a warning. The app must be published;
guests are limited to 120 requests per minute and address (`PUBLIC_RATE`).

The **Input field** block (group "Scripts") has a name such as `firstname`.
When someone clicks a script button on the same page, all input fields are
sent along and the script reads them as `params["firstname"]`. For pages that
should only work with a specific link, create a code with `token()` in a
script, store it on the entry, and check `params["code"]` on the page.

Scripts also have `session`, a small store per visitor (browser) and app that
survives page loads, for guests too (at most 4 KB of plain values). Use it to
remember what a visitor already did, for example the id of their answer, so a
reload shows it and a second click updates instead of duplicating.

### External data sources

A data source can mirror data from a supported SQL database or Databricks.
Queries must be read-only (`SELECT` or `WITH`). Configure the connection,
query, refresh interval, and optional key field in the Designer. Set limits
and timeouts appropriate for the source.

## 3. Developing

### Running locally

Install the requirements, set `DEBUG=1`, and run:

```text
python manage.py migrate
python manage.py runserver
```

The application is then available at `http://127.0.0.1:8000/`.

### Code structure and Python extensions

The Django project is in `config/`; the application code is in `builder/`.
Custom Python extensions belong in `extensions/`. Keep extensions small,
validate input, and expose only the API endpoints that are required.

### API

Enable the API for a table in the Designer and create an API key with the
required permissions. Send it in every request:

```text
Authorization: Bearer bk_...
```

The interactive API documentation is available from **API documentation**.
The OpenAPI document can be imported into Postman, Insomnia, or a code
generator. API responses use JSON and field short names.

### Tableau

The **Tableau view** block embeds a dashboard from your Tableau Server or
Tableau Cloud using Tableau's Embedding API v3. Enter the dashboard address
(e.g. `https://tableau.company.com/views/Plants/Overview`), optionally a title,
height, toolbar position, and filters, one per line as `Field = Value`;
`{name}` takes the value from the page address (`?name=…`).

Without further setup, users sign in to Tableau themselves. With a Tableau
**Connected App** (Direct Trust), Baukasten signs signed-in users in with a
5-minute embed-only token. Operators set `TABLEAU_HOSTS` (allowed servers),
optionally `TABLEAU_CONNECTED_APP_CLIENT_ID`, `TABLEAU_CONNECTED_APP_SECRET_ID`,
`TABLEAU_CONNECTED_APP_SECRET_VALUE` (keep it in the Secret), and
`TABLEAU_USER_ATTRIBUTE` (`email` or `username`). Tableau views are not shown on
public pages.

### MCP server

Each app is an MCP server (Model Context Protocol) at `/mcp/<app>/`, so AI
agents such as n8n, Claude, or Cursor can use its tables as tools.

- Transport: "HTTP Streamable" without streaming; every request is a POST with
  one JSON-RPC message. There is no SSE stream.
- Authentication: an API key of the app, sent as `Authorization: Bearer bk_...`.
  A key without write permission only gets the read tools.
- Tools are generated from the tables enabled for the API: `list_<table>`,
  `get_<table>`, and with write permission `create_<table>`, `update_<table>`,
  `delete_<table>` where the table allows it. Custom endpoints from
  `extensions` appear as `x_<name>`. Field labels, types, required fields, and
  choices become the tool input schema.

To connect n8n, add an **AI Agent** with the **MCP Client Tool**: endpoint
`https://<host>/mcp/<app>/` (n8n in Docker against Docker Desktop:
`http://host.docker.internal:8080/mcp/<app>/`), transport "HTTP Streamable",
authentication "Bearer Auth" with the key. The host n8n uses must be listed in
`ALLOWED_HOSTS`.

### Translations

The application UI uses Django translations. German is the source language;
English translations are stored in `builder/locale/en/LC_MESSAGES/`. After
changing translatable strings, regenerate the message file and compile it.
The handbook uses the language-specific files in `docs/`.

## 4. Operating

### Configuration

Production settings come from environment variables. Set `SECRET_KEY`,
`ALLOWED_HOSTS`, the database URL, and the required authentication settings.
Use Redis for shared cache and coordination when running multiple pods.

### Kubernetes

The manifests in `k8s/` run Baukasten with a web deployment, migrations,
background jobs, and the required database or cache services. Apply migrations
before routing traffic to a new version.

### Scaling and background work

Gunicorn workers and threads determine web concurrency. Keep database
connection limits in mind. Query concurrency and timeouts for external data
sources should be configured so that slow warehouses cannot exhaust web
workers. Background jobs execute scheduled scripts and data-source syncs.

### Authentication, permissions, and administration

Keycloak can provide single sign-on and group membership. Users need the
appropriate app and table permissions. The `/admin/` area is for administrators
and should not be exposed without authentication and transport security.

### Security and backups

Use HTTPS, protect secrets in deployment configuration, and issue narrowly
scoped API keys. Back up the database and test restoring it. Do not put
credentials in scripts, extensions, or exported app definitions.

## Frequently asked questions

**Why can I not see an app?** Check that it is published and that your user or
group has access.

**Why can I not find an app in the Designer?** It belongs to someone else. Ask
its owner to add you as a co-editor.

**Why is a table missing from the API?** Enable the table for the API and use a
key that belongs to the same app.

**Why does the page show stale external data?** Check the source refresh
interval, the background worker, and the query cache settings.

**How do I switch the handbook back to German?** Select **DE** in the language
switch at the top right. The choice is kept in your session.

## Current limitations

The available blocks, data-source adapters, and script APIs are determined by
the installed version and its configuration. Test integrations with realistic
data and load before using them in production.

## Glossary

| Term | Meaning |
|---|---|
| App | An application containing tables, pages, and configuration |
| Block | A reusable page component |
| Designer | The interface for building and configuring apps |
| Entity / table | A collection of related entries |
| Field | A property of an entry |
| Entry / record | One row of data in a table |
| API key | A credential for API or MCP access |
| Version | A saved state of an app configuration |
