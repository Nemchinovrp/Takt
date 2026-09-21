import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

DEFAULT_FIGIS = ("BBG004730N88", "BBG004730RP0", "BBG004731032", "BBG006L8G4H1")


@dataclass(frozen=True)
class Config:
    mode: str = "demo"
    token: str = field(default="", repr=False)
    account_id: str = ""
    figis: tuple[str, ...] = DEFAULT_FIGIS
    poll_seconds: int = 15

    def __post_init__(self):
        if self.mode not in {"demo", "sandbox", "readonly"}:
            raise ValueError("INVEST_MODE: допустимы demo, sandbox, readonly")
        if self.mode != "demo" and not self.token:
            raise ValueError("Для подключения нужен TINKOFF_TOKEN в файле .env")
        if not 5 <= self.poll_seconds <= 3600:
            raise ValueError("INVEST_POLL_SECONDS должен быть от 5 до 3600")
        if not self.figis or len(self.figis) > 20:
            raise ValueError("Укажите от 1 до 20 FIGI в INVEST_FIGIS")

    @classmethod
    def from_env(cls, mode=None):
        load_dotenv()
        return cls(
            mode=mode or os.getenv("INVEST_MODE", "demo"),
            token=os.getenv("TINKOFF_TOKEN", "").strip(),
            account_id=os.getenv("TINKOFF_ACCOUNT_ID", "").strip(),
            figis=tuple(dict.fromkeys(x.strip() for x in os.getenv(
                "INVEST_FIGIS", ",".join(DEFAULT_FIGIS)
            ).split(",") if x.strip())),
            poll_seconds=int(os.getenv("INVEST_POLL_SECONDS", "15")),
        )

