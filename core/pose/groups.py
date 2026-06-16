"""
Keypoint group definitions.

ViTPose wholebody emits 133 keypoints in the COCO-WholeBody layout:

    0-16   body   (17)
    17-22  feet   (6)   -> grouped with body
    23-90  face   (68)
    91-132 hands  (42)  (left 91-111, right 112-132)

A "keypoint group" selects which of these are drawn and recorded. The model
always computes all of them in one forward pass (the cost lives in the ViT
backbone, not the head), so groups are purely a visualization/recording filter
and switching between them is free at inference time.
"""

# Display/record groups, ordered from lightest to fullest.
KEYPOINT_GROUPS = ["body", "body_face", "body_hands", "wholebody"]

# Human-readable labels for the GUI.
KEYPOINT_GROUP_LABELS = {
    "body": "Body",
    "body_face": "Body + Face",
    "body_hands": "Body + Hands",
    "wholebody": "Full (Body + Face + Hands)",
}

# Index ranges within the 133-keypoint wholebody layout.
_BODY = set(range(0, 23))      # body + feet
_FACE = set(range(23, 91))     # face mesh
_HANDS = set(range(91, 133))   # both hands

# Which keypoint indices each group keeps (for the wholebody dataset).
WHOLEBODY_GROUP_INDICES = {
    "body": _BODY,
    "body_face": _BODY | _FACE,
    "body_hands": _BODY | _HANDS,
    "wholebody": _BODY | _FACE | _HANDS,
}


def active_indices(dataset: str, group: str, num_keypoints: int) -> set:
    """
    Return the set of keypoint indices kept for a (dataset, group) pair.

    For non-wholebody datasets (e.g. coco-17) every keypoint is body, so all
    indices are kept regardless of the requested group.
    """
    if dataset == "wholebody":
        return WHOLEBODY_GROUP_INDICES.get(group, WHOLEBODY_GROUP_INDICES["wholebody"])
    return set(range(num_keypoints))
