VOKK Next.js port status

What is real now
- Created this folder with create-next-app.
- Added a same-origin Next proxy at `src/app/api/vokk/[...path]/route.ts` so the Next app can call the current local VOKK backend without cross-origin browser issues.
- Replaced the starter template with a much larger native shell in `src/app/page.tsx`.
- Native shell now includes:
  - login or guest gate
  - auth method picker UI
  - sidebar with chat/artifact/note rails
  - search box
  - session list and active chat state
  - chat message stream
  - mode toggle and model picker
  - same-origin chat calls into the live backend
  - note/artifact local state
  - full-app bridge tab for the remaining unported surface
- Updated app metadata and styling to match the VOKK rebuild direction.
- The default backend target for the Next proxy is the current local VOKK host on `http://127.0.0.1:8777`.
- `npm run lint` passes.
- `npm run build` passes.

What is honest right now
- This is still not a full native rewrite of the complete app.
- The native shell is now much broader than before, but it does not yet cover all features from `vokk.py`.
- The bridge tab still exists because preview engine, VOKK-DO, archive/memory tools, richer artifact rendering, and full history parity are not fully native yet.
- The backend is still the current Python/VOKK runtime, not a full Next backend rewrite.

What is next
- Port preview engine into native Next panels.
- Port memory/context tools and archive actions.
- Port VOKK-DO panels and permission flows.
- Port richer chat bubble features like trace expanders, code preview affordances, and media artifacts.
- Remove the bridge tab as those features become native.

Why this file exists
- The request was to create a new Next.js folder and rebuild the app there.
- This file states exactly what is already native, what still depends on the old runtime, and what remains.
