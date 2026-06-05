from vokk import Handler, init_auth_db


# Ensure the local auth/memory schema exists when the function cold-starts.
init_auth_db()


class handler(Handler):
    pass
