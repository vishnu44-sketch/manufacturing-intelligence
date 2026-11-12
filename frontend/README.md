# Manufacturing Intelligence - React app

The whole website: Login, Ask AI (chats, edit a question, saved answers, Excel), History (with the AI
usage box), and for staff Users, Documents and Data. It talks only to the Django JSON API under
`/api/` (portal/api.py). Django serves the built `index.html` at `/` and at every page address
(`/history`, `/c/5`, ...); the Django admin stays at `/admin/` with its own sign-in.

Run these in this `frontend` folder (Node 22.13 or newer):

- `npm install` - the packages (exact versions, see package.json).
- `npm run dev` - the dev server on http://localhost:5173. It sends `/api`, `/admin` and `/static`
  on to the Django runserver on http://127.0.0.1:8081, so start that first:
  `python manage.py runserver 8081`.
- `npm run build` - type-checks, then writes the app into `portal/static/portal/app/`.
  Django then serves it at http://127.0.0.1:8081/ (not in git: build it on each machine).
- `npm test` - the Vitest tests (no server, no AI).
- `npm run typecheck` - TypeScript only.

The look is `src/styles/app.css` (moved here from the old Django pages) plus `src/extra.css`.
