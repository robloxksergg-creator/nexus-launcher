from __future__ import annotations

from dataclasses import dataclass

from zxcvbn import zxcvbn

APP_TERMS = {
    "nexus",
    "nexus123",
    "nexusmc",
    "minecraft",
    "neoforge",
    "fabric",
    "controlpanel",
    "administrator",
}
SEQUENCES = ("123456", "12345678", "qwerty", "abcdef", "letmein", "welcome", "password")
LEVELS = ("Очень слабый", "Слабый", "Нормальный", "Хороший", "Очень хороший")


@dataclass(frozen=True)
class PasswordAssessment:
    accepted: bool
    score: int
    level: str
    reasons: tuple[str, ...]


class PasswordService:
    def __init__(self, minimum_length: int = 12, privileged_recommended_length: int = 15, maximum_length: int = 256):
        self.minimum_length = minimum_length
        self.privileged_recommended_length = privileged_recommended_length
        self.maximum_length = max(64, maximum_length)

    def assess(self, password: str, username: str = "", context_words: tuple[str, ...] = ()) -> PasswordAssessment:
        reasons = []
        if len(password) < self.minimum_length:
            reasons.append(f"Пароль должен содержать не менее {self.minimum_length} символов.")
        if len(password) > self.maximum_length:
            reasons.append(f"Пароль не должен превышать {self.maximum_length} символов.")
        lowered = password.casefold()
        normalized_username = username.strip().casefold()
        if normalized_username and len(normalized_username) >= 3 and normalized_username in lowered:
            reasons.append("Не используйте имя пользователя в пароле.")
        found_terms = sorted(term for term in APP_TERMS if term in lowered)
        if found_terms:
            reasons.append("Пароль содержит название NEXUS/Minecraft или другой предсказуемый термин.")
        if any(sequence in lowered for sequence in SEQUENCES):
            reasons.append("Пароль содержит распространённую или предсказуемую последовательность.")
        result = (
            zxcvbn(
                password,
                user_inputs=[username, "NEXUS", "Minecraft", *context_words],
                max_length=self.maximum_length,
            )
            if password
            else {"score": 0}
        )
        score = int(result.get("score", 0))
        feedback = result.get("feedback", {})
        warning = str(feedback.get("warning", "")).strip()
        if warning and score < 3:
            reasons.append("Этот пароль слишком распространён или легко угадывается.")
        accepted = not reasons and score >= 3
        if score < 3 and not reasons:
            reasons.append("Используйте более длинную уникальную парольную фразу.")
        return PasswordAssessment(accepted, score, LEVELS[score], tuple(dict.fromkeys(reasons)))

    def validate(self, password: str, username: str = "", context_words: tuple[str, ...] = ()) -> PasswordAssessment:
        assessment = self.assess(password, username, context_words)
        if not assessment.accepted:
            raise ValueError("\n".join(assessment.reasons))
        return assessment
