"""Context segment SPI and its Turn-owned collection."""

from .protocol import (
    ContextSegment,
    UpdatingSegment,
    SegmentProvider,
    SegmentDescriptor,
    SegmentSlot,
    SegmentShape,
    SegmentCapability,
    TurnInfo,
    SegmentProjection,
    SegmentReclaim,
    InspectableSegment,
    SelectableSegment,
    ReclaimableSegment,
)
from .registration import (
    RegisteredSegment,
    ReadOnlySegmentRegistration,
    SegmentRegistration,
)
from .collection import SegmentRegistry, PreparedSegmentBatch, TurnSegments
