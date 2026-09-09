class RelayError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        self.code, self.message, self.status = code, message, status

    def envelope(self) -> dict:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}
