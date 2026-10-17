"""Typed interface settings mutations."""

from pydantic import BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

from tinysoul.gateway.presentation import (
    InterfaceDensity,
    InterfaceSettingsPatch,
    MonoFont,
    SansFont,
    ThemeMode,
)


class InterfaceChangesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme: ThemeMode | None = None
    font_sans: SansFont | None = None
    font_mono: MonoFont | None = None
    font_size: int | None = Field(default=None, strict=True, ge=12, le=18)
    line_height: float | None = Field(default=None, strict=True, ge=1.3, le=1.9)
    density: InterfaceDensity | None = None
    reduced_motion: bool | None = Field(default=None, strict=True)

    def model_post_init(self, __context: object) -> None:
        if not self.model_fields_set or any(
            getattr(self, name) is None for name in self.model_fields_set
        ):
            raise PydanticCustomError(
                "interface_changes", "Changes require non-null field values"
            )

    def to_patch(self) -> InterfaceSettingsPatch:
        return InterfaceSettingsPatch(
            theme=self.theme,
            font_sans=self.font_sans,
            font_mono=self.font_mono,
            font_size=self.font_size,
            line_height=self.line_height,
            density=self.density,
            reduced_motion=self.reduced_motion,
        )


class PresentationPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    changes: InterfaceChangesRequest
