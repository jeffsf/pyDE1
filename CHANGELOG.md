# Changelog

## Pending for 0.3.0

### New

`BleakClientWrapped.willful_disconnect` property can be used to determine if the on-disconnect callback was called as a result of an intentional (locally initiated) or unintentional disconnect.

`BleakClientWrapped.name` provides the advertised device name under BlueZ and shoud not fail under macOS (or Windows).

### Fixed

Python 3.8 compatibility: Changed "subscripted" type hints for `dict`, `list`, and `set` to their capitalized versions from `typing`

### Changed

`DE1`, `FlowSequencer`, and `ScaleProcessor` are now `Singleton`.

`DE1()` and `Scale()` no longer accept an address as an argument. Use the `.address` property.

`BleakClientWrapped` unifies `atexit` to close connected devices. 

### Deprecated

### Removed

`DE1()` and `Scale()` no longer accept an address as an argument. Use the `.address` property.