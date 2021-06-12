"""
For the Mapping to work properly, when it comes time to get or set a value
the code needs to be able to access the setter or getter by path string
and determine if it is a standard function or a coroutine.

It doesn't make a lot of sense for a property to define an async setter as
    await target = value
doesn't seem like a natural construct at all.

Summary:
  * Normal getters work with getattr() as-is, if they exist
  * Normal setters work with setattr() as-is, if they exist
  * If the don't exist: AttributeError: unreadable attribute

  * Just avoid defining async versions
    * Which report as inspect.isfunction() and inspect.iscoroutinefunction()
      and not inspect.coroutine()
    * Even if they are available through type(target).field.fset or .fget
"""

import asyncio
import inspect
from pyDE1.utils_public import rgetattr, rsetattr

class ChildClass:
    def __init__(self):
        self.direct = 'direct'
        self._standard_property = 'standard property'
        self._read_only_property = 'read-only property'
        self._standard_property_async = 'standard property, async setter'

    @property
    def standard_property(self):
        return self._standard_property

    @standard_property.setter
    def standard_property(self, value):
        self._standard_property = value


    @property
    def read_only_property(self):
        return self._read_only_property

    def write_only_property_internal(self, value):
        print(f"Write-only property gets '{value}'")

    # c.write_only_property
    # Traceback (most recent call last):
    #   File "<input>", line 1, in <module>
    # AttributeError: unreadable attribute
    write_only_property = property(fset = write_only_property_internal)


    @property
    def standard_property_async_set(self):
        return self._standard_property_async

    @standard_property_async_set.setter
    async def standard_property_async_set(self, value):
        self._standard_property_async = value


    async def write_only_property_async_internal(self, value):
        print(f"Write-only async property gets '{value}'")

    # pyCharm shows a type-check error here
    write_only_property_async = property(
        fset = write_only_property_async_internal)


class ParentClass:
    def __init__(self):
        self._child = ChildClass()

    @property
    def child(self):
        return self._child


if __name__ == '__main__':

    test = ParentClass()

    attr_standard_property = rgetattr(test, 'child.standard_property')
    attr_read_only_property = rgetattr(test, 'child.read_only_property')
    # AttributeError: unreadable attribute
    # attr_write_only_property = rgetattr(test, 'child.write_only_property')
    attr_standard_property_async_set = \
        rgetattr(test, 'child.standard_property_async_set')
    # AttributeError: unreadable attribute
    # attr_write_only_property_async = \
    #     rgetattr(test, 'child.write_only_property_async')

    for a in (
            attr_standard_property,
            attr_read_only_property,
            # attr_write_only_property,
            attr_standard_property_async_set,
            # attr_write_only_property_async
    ):
        print(
            f"{a}"
        )
    # "Straight" getattr works:
    # standard property
    # read-only property
    # standard property

    rsetattr(test, 'child.standard_property', 'set standard')
    print(test.child.standard_property)

    # AttributeError: can't set attribute
    # rsetattr(test, 'child.read_only_property', 'set read-only')
    # print(test.child.read_only_property)

    rsetattr(test, 'child.write_only_property', 'set write-only')

    # RuntimeWarning: coroutine 'ChildClass.standard_property_async_set' was never awaited
    # This try/catch does not catch
    # try:
    #     rsetattr(test, 'child.standard_property_async_set', 'set async')
    #     print(test.child.standard_property_async_set)
    # except RuntimeWarning as e:
    #     print(f"Async set failed: {e}")

    # Reasonable to assume this fails the same way
    # rsetattr(test, 'child.write_only_property_async', 'set async')

    print(f"instance: {test.child.standard_property_async_set}")
    print(f"class: {type(test.child).standard_property_async_set}")
    fset = type(test.child).standard_property_async_set.fset
    print(f"fset: {fset}")
    print(f"isfunction: {inspect.isfunction(fset)}")
    print(f"isroutine: {inspect.isroutine(fset)}")
    print(f"iscoroutine: {inspect.iscoroutine(fset)}")
    print(f"iscoroutinefunction: {inspect.iscoroutinefunction(fset)}")
    print(f"isawaitable: {inspect.isawaitable(fset)}")
    # class: <property object at 0x103da7400>
    # fset: <function ChildClass.standard_property_async_set at 0x103da68b0>
    # isfunction: True
    # iscoroutine: False
    # iscoroutinefunction: True
    # isawaitable: False

    async def try_async_set(parent: ParentClass):
        i_fset = type(parent.child).standard_property_async_set.fset
        print(f"before: {parent.child.standard_property_async_set}")
        await i_fset(parent.child, "async-set value")
        print(f"after: {parent.child.standard_property_async_set}")
        # Fails with AttributeError: unreadable attribute
        # await parent.child.write_only_property_async("set running async")
        await parent.child.write_only_property_async_internal(
            "set running async")

    loop = asyncio.get_event_loop()
    loop.set_debug(True)
    loop.run_until_complete(try_async_set(test))
