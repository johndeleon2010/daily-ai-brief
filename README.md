# Daily AI Brief

Weekday briefing pipeline and lightweight GitHub Pages card dashboard for selected AI creators.

## Schedule

GitHub Actions checks at 7:00 AM in `America/Los_Angeles`, Monday through Friday. Two UTC schedules handle daylight saving time, and a local time gate prevents duplicate runs. The earlier start leaves time for delivery near 7:30 AM when GitHub queues a scheduled run.

## Outputs

* `docs/data/latest.json` for the unlisted dashboard
* `docs/data/YYYY-MM-DD.json` for history
* `docs/data/archive.json` for the searchable dashboard archive
* `docs/feed.xml` for delivery through Power Automate
* Notion content and daily archive records when `NOTION_TOKEN` is configured

## Browser delivery

Download the `delivery` folder to a Windows computer. Run `Install-BrowserPopup.cmd` while signed in as the person who should receive the brief. The scheduled task checks the live data every five minutes after 7:30 AM on weekdays. Microsoft Edge opens only after the published date matches the current date.

## Email delivery

Create a Power Automate cloud flow with the RSS trigger named `When a feed item is published`.

Feed URL: `https://johndeleon2010.github.io/daily-ai-brief/feed.xml`

Add the Office 365 Outlook action named `Send an email (V2)`. Use the RSS title for the subject, the RSS summary for the message, and the primary feed link for the dashboard button. This keeps Outlook credentials out of GitHub.

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

Every card includes a key paragraph, three takeaways, and a practical ELI10 task based on the source method. A source without a clear method gets a small experiment based on its main idea. The selector limits each creator to two cards, removes duplicate video identifiers, favors recent content, and labels fallback summaries when no AI key exists.
