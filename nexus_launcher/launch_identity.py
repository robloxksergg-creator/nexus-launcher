"""Bind delayed game-ticket issuance to the account selected before preparation."""


def ticket_supplier(profile, client, current_profile, current_client):
    def verify():
        if current_profile() is not profile or current_client() is not client:
            raise PermissionError("Аккаунт изменён во время подготовки. Повторите запуск.")

    def issue():
        verify()
        ticket = client.game_ticket_for(profile)
        verify()
        return ticket

    return issue
