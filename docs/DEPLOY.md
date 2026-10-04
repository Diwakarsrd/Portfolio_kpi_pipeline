# Deploy (Streamlit Community Cloud)

I verified the app runs headless (`streamlit.testing`, both scenarios, no exceptions). I could not deploy it from the build sandbox, so these steps are untested end to end.

1. Push this folder to a public GitHub repo (the synthetic `data/` and `outputs/` folders are small and meant to be committed).
2. share.streamlit.io -> New app -> repo, branch `main`, main file `app.py`, Python 3.12.
3. (Optional) Secrets -> `GROQ_API_KEY = "..."` to enable live LLM suggestions/commentary. Without it the app and pipeline use the deterministic template and show that clearly.
4. First load: if `outputs/` is missing the app builds it once (about a second).
5. Put the live URL at the top of the README.

If the build fails, the usual causes are a missing dependency in `requirements.txt` or the wrong main-file path.
