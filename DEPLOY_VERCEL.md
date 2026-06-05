# VOKK on Vercel

Current state:
- Vercel entrypoint: `api/index.py`
- Runtime config: `vercel.json`
- Python pin: `.python-version`

What still needs a real deploy:
1. `vercel login` or `vercel --token ...`
2. Add env vars in Vercel Project Settings from `~/.vokk/secrets.env`
3. Run `vercel`
4. Verify:
   - `/`
   - `/api/status`
   - guest chat
   - login flow

Important:
- This prepares VOKK for Vercel's Python runtime.
- It does not prove production behavior until a live deploy is verified.
- VOKK is still mainly hosted by Python code in `vokk.py`; this is deploy prep, not a full VOKK-script-only runtime.
