# First-Time GitHub Publishing

This project should be published from the `FilmLog_project` directory, not from its parent directory.

## Safety Checklist

Before publishing:

- Rotate any API keys that were ever saved locally.
- Keep `.env`, `filmlog.db`, personal photos, generated thumbnails, generated index sheets, API CSV files, and local font files out of Git.
- Use the Git repository inside `FilmLog_project`, not the parent `Code` repository.

## Create the First Commit

```bash
cd FilmLog_project
git init
git add .
git status
git commit -m "Initial open source release"
```

## Push to GitHub

Create an empty GitHub repository named `FilmLog` without adding a README, license, or `.gitignore`, then run:

```bash
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/FilmLog.git
git push -u origin main
```

If Git asks who you are:

```bash
git config --global user.name "YOUR_NAME"
git config --global user.email "YOUR_EMAIL"
```

If GitHub rejects password login, use GitHub Desktop, GitHub CLI, or a personal access token instead of your account password.
