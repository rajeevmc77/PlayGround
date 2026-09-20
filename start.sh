source venv/bin/activate
export SESSION_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
python -m uvicorn app:app --reload