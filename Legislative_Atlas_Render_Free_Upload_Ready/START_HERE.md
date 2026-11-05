# Legislative Atlas: GitHub + Render free deployment

This is the minimal deployable v1.2.6 project. Its `render.yaml` explicitly sets `plan: free`; confirm the Render review page shows $0 for the web service before approval.

## GitHub (browser only)
1. Create a PRIVATE repository named `legislative-atlas` at https://github.com/new . Do not initialize it with a README.
2. Unzip this package on your Mac.
3. Open the new repository, click **uploading an existing file** or **Add file > Upload files**.
4. In Finder, open the extracted `Legislative_Atlas_Render_Free_v1_2_6` folder and drag the FILES AND FOLDERS INSIDE IT to the upload drop zone. All required files should be at the repository ROOT, not under a nested folder. The key files are `render.yaml`, `Dockerfile`, `index.html`, `live_server.py` and `result_store.py`.
5. Click Commit changes. Do not upload your Mac's local `runtime/` folder, personal data, or credentials.

## Render
1. Sign in to https://dashboard.render.com .
2. Choose **New > Blueprint**. Authorize Render to access the GitHub repository if prompted.
3. Select the `legislative-atlas` repository, default `main` branch, and `render.yaml` at root.
4. Review the planned service `us-legislative-atlas-2026`. Confirm `plan: free` / $0 before clicking deploy; do not approve a paid plan by mistake.
5. When Live, open your assigned https://...onrender.com/ URL. Test /api/health, /api/coverage, and select Utah on the map.
6. Share that HTTPS URL with Ali.

## IMPORTANT LIMITATIONS
- Render Free instances sleep after 15 min without traffic and may take around a minute to wake; their filesystem is **ephemeral**. Previously downloaded state snapshots and roster cache can vanish on redeploy, restart, or sleep. This web app has Utah, Guam and Virgin Islands seed snapshots compiled in; other result feeds may or may not return data. A paid persistent disk or a different durable-storage implementation is required to preserve changing feeds long term.
- Live data feeds are NOT validated nationwide; 2026 results must be checked against source links. Do not treat uncited gray districts as zero votes or a race call.
- The web URL is PUBLIC unless additional authentication is implemented. A private GitHub source repository does NOT make the website private. Do not include confidential data in the app or repository.
- The current app checks the SELECTED state when a page is open; there is NO always-on nationwide background update job. When no one is browsing, it does not poll the entire election.
- The service contacts civicAPI, MultiState and other sources. Check providers' usage rules/permissions before extensive automated use.

Sources: https://render.com/docs/free https://render.com/docs/infrastructure-as-code https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository
