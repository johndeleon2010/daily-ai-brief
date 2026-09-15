# Daily AI Brief

Weekday briefing pipeline and lightweight GitHub Pages card dashboard for selected AI creators.

## Schedule

GitHub Actions checks at 7:30 AM in `America/Los_Angeles`, Monday through Friday. Two UTC schedules handle daylight saving time, and a local time gate prevents duplicate runs.

## Outputs

* `docs/data/latest.json` for the unlisted dashboard
* `docs/data/YYYY-MM-DD.json` for history
* `docs/data/archive.json` for the searchable dashboard archive
* Notion content and daily archive records when `NOTION_TOKEN` is configured

## Required repository secrets

* `NOTION_TOKEN`, an internal Notion integration shared with the Daily AI Brief page
* `OPENAI_API_KEY`, optional, for richer summaries and action recommendations

The Notion data source identifiers are stored as workflow variables because identifiers are not credentials.

## GitHub Pages

In repository Settings, open Pages. Set the source to Deploy from a branch, choose `main`, choose `/docs`, and save.

## Run locally

`python src/generate_brief.py --force`

## Test

`python -m unittest discover -s tests -v`

## Editorial controls

Every card includes an original source URL and a practical ELI10 action for SQL, automation, AI agents, or IT operations. The selector limits each creator to two cards, removes duplicate video identifiers, favors recent content, and labels fallback summaries when no AI key exists.
