"""RiskCalc HTTP bridge.

A thin localhost JSON layer over the existing dict-returning services, so a
native client (the SwiftUI app under `macapp/`) can drive the unchanged Python
pricing engine. No engine logic lives here — only transport and serialization.
"""
