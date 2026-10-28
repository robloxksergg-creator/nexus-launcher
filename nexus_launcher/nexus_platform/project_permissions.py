"""Fail-closed project authorization contract for future service integration.

Only verified service data may construct this context. Not a session validator,
not wired to publication yet; browser flags and locally authored text are excluded.
"""
from dataclasses import dataclass
from enum import Enum


class ProjectRole(str, Enum):
    VIEWER = "viewer"
    MEMBER = "member"
    CREATOR = "creator"


@dataclass(frozen=True)
class ProjectAccess:
    subject_id: str | None = None
    creator_id: str | None = None
    session_verified: bool = False
    project_verified: bool = False

    @property
    def role(self) -> ProjectRole:
        if (self.session_verified and self.project_verified and self.subject_id
                and self.creator_id and self.subject_id == self.creator_id):
            return ProjectRole.CREATOR
        return ProjectRole.MEMBER if self.session_verified and self.subject_id else ProjectRole.VIEWER

    def require_edit(self) -> None:
        if self.role is not ProjectRole.CREATOR:
            raise PermissionError("Only the verified project creator may edit this project")
