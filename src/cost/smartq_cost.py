"""
SmartQ cost model.

Scaffold for the SmartQ-specific costing model, which layers on top of the
shared overall-cost scaling in ``src.cost.overall_cost``. The model itself is
specified separately; this module is the home for its pure arithmetic so it
stays unit-testable and decoupled from the vendor-cost model.

The ``ui.smartq_cost`` layer renders whatever lands here.
"""
