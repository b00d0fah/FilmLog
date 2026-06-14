# Film Strip Templates

Directory layout:

- `assets/film_strips/135/`
- `assets/film_strips/120/`

Each film type directory contains:

- One shared sprocket overlay for that format when needed.
  - Example: `assets/film_strips/135/sprocket_strip.png`
- One folder per strip template.
  - Example: `assets/film_strips/135/kodak-gc-400/`

Template folder naming:

- Lowercase ASCII.
- Use hyphens for separators.
- Example: `kodak-gc-400`, `portra-400`, `ilford-hp5-plus`.

Template file naming inside a folder:

- Use six-frame segment filenames.
- `1-6.png`, `7-12.png`, `13-18.png`, `19-24.png`, `25-30.png`, `31-36.png`, `37-42.png`

Generation rules:

1. The app chooses the template folder from the selected strip template.
2. It picks the segment file by embedded frame range.
3. It pastes photos first.
4. For 135, it pastes the shared sprocket overlay on top.

Current built-in assets:

- `135/kodak-gc-400/`
- shared `135/sprocket_strip.png`
