"""Dialogue-track domain services (ADR 0003).

The speech track's domain logic lives here rather than inside the scene-3d
package: it is shared by the voice-cast node, the timeline, the alignment
surface and the lip-sync path, and scene-3d is only one of its consumers.
"""
