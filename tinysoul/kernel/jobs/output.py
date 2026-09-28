"""Opaque independent channel positions for non-consuming Job output reads."""

from __future__ import annotations

from dataclasses import dataclass

from tinysoul.infra.continuation import (
    ContinuationError,
    ContinuationFailureReason,
    ContinuationPosition,
    OpaqueContinuationCodec,
)


@dataclass(frozen=True)
class JobOutputPosition:
    offsets: tuple[int, ...]

    @classmethod
    def decode(
        cls, token: str | None, *, job_id: str, channels: tuple[str, ...]
    ) -> JobOutputPosition:
        codec = OpaqueContinuationCodec(owner="jobs", operation="output")
        tokens = token.split("~") if token else [None] * len(channels)
        if len(tokens) != len(channels):
            raise ContinuationError(
                ContinuationFailureReason.MISMATCH,
                "Job output continuation has different channels",
            )
        return cls(
            tuple(
                codec.decode(item, ref=f"{job_id}:{channel}").item_index
                for channel, item in zip(channels, tokens, strict=True)
            )
        )

    def encode(self, *, job_id: str, channels: tuple[str, ...]) -> str:
        codec = OpaqueContinuationCodec(owner="jobs", operation="output")
        return "~".join(
            codec.encode(
                ContinuationPosition(item_index=offset), ref=f"{job_id}:{channel}"
            )
            for channel, offset in zip(channels, self.offsets, strict=True)
        )
