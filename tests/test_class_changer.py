"""
Copyright © 2022 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only
"""
import pytest
import typing

import pyDE1
import pyDE1.de1
from pyDE1.bledev.managed_bleak_device import ManagedBleakDevice, ClassChanger, \
    class_changer_generic_class


class TestA:

    def __init__(self):
        self.name = 'TestA initial'

    def tell_name(self):
        return self.name

    def tell_class(self):
        return self.__class__

class TestB:

    def __init__(self):
        self.name = 'TestB initial'

    def tell_name(self):
        return self.name

    def tell_class(self):
        return self.__class__

@pytest.mark.xfail
def test_assumptions_around_moving_methods():

    a0 = TestA()
    b0 = TestB()

    assert a0.tell_name() == 'TestA initial'
    assert b0.tell_name() == 'TestB initial'
    assert a0.tell_class() == TestA
    assert b0.tell_class() == TestB

    a1 = TestA()
    a1.name = 'newA'

    assert a1.tell_name != a0.tell_name

    assert a1.tell_name() == 'newA'

    print()
    print(f"a0: {a0.tell_name} with self: {a0.tell_name.__self__}")
    print(f"a1: {a1.tell_name} with self: {a1.tell_name.__self__}")

    setattr(a0, 'tell_name', getattr(a1, 'tell_name'))

    print("after")
    print(f"a0: {a0.tell_name} with self: {a0.tell_name.__self__}")
    print(f"a1: {a1.tell_name} with self: {a1.tell_name.__self__}")

    assert a1.tell_name == a0.tell_name

    assert a0.tell_name() == 'TestA initial'
    assert a1.tell_name() == 'newA'

class Parent:

    def __init__(self):
        self.p = 'p'

    def get_class(self):
        return self.__class__

    def get_type(self):
        return type(self)

    def get_hard_class(self):
        return 'Parent'


class SubtypeA (Parent):

    def __init__(self):
        super(SubtypeA, self).__init__()
        self.a = 'self.a'

    def get_hard_class(self):
        return 'SubtypeA'

    def method_a(self):
        return 'SubtypeA method_a'

    def get_local(self):
        return self.a

class SubtypeB(Parent):

    def __init__(self):
        super(SubtypeB, self).__init__()
        self.b = 'self.b'

    def get_hard_class(self):
        return 'SubtypeB'

    def method_b(self):
        return 'SubtypeB method_b'

    def get_local(self):
        return self.b

def test_changing_class():

    p = Parent()
    a = SubtypeA()
    b = SubtypeB()

    assert isinstance(p, Parent)
    assert isinstance(a, SubtypeA)
    assert isinstance(b, SubtypeB)

    assert p.get_hard_class() == 'Parent'
    assert p.get_class() == Parent
    assert p.get_type() == Parent
    assert p.__class__ == Parent
    assert not hasattr(p, 'method_a')
    assert not hasattr(p, 'method_b')
    assert not hasattr(p, 'get_local')

    assert a.get_hard_class() == 'SubtypeA'
    assert a.get_class() == SubtypeA
    assert a.get_type() == SubtypeA
    assert a.__class__ == SubtypeA
    assert     hasattr(a, 'method_a')
    assert not hasattr(a, 'method_b')
    assert     hasattr(a, 'get_local')
    assert a.method_a() == 'SubtypeA method_a'
    with pytest.raises(AttributeError):
        a.method_b()
    assert a.get_local() == 'self.a'

    assert b.get_hard_class() == 'SubtypeB'
    assert b.get_class() == SubtypeB
    assert b.get_type() == SubtypeB
    assert b.__class__ == SubtypeB
    assert not hasattr(b, 'method_a')
    assert     hasattr(b, 'method_b')
    assert     hasattr(b, 'get_local')
    with pytest.raises(AttributeError):
        b.method_a()
    assert b.method_b() == 'SubtypeB method_b'
    assert b.get_local() == 'self.b'

    a.__class__ = SubtypeB
    assert a.get_hard_class() == 'SubtypeB'
    assert a.get_class() == SubtypeB
    assert a.get_type() == SubtypeB
    assert a.__class__ == SubtypeB
    assert not hasattr(b, 'method_a')
    assert     hasattr(b, 'method_b')
    assert     hasattr(b, 'get_local')
    with pytest.raises(AttributeError):
        a.method_a()
    assert a.method_b() == 'SubtypeB method_b'
    with pytest.raises(AttributeError):
        a.get_local()

    b.__class__ = Parent
    assert b.get_hard_class() == 'Parent'
    assert b.get_class() == Parent
    assert b.get_type() == Parent
    assert b.__class__ == Parent
    assert not hasattr(b, 'method_a')
    assert not hasattr(b, 'method_b')
    assert not hasattr(b, 'get_local')

@class_changer_generic_class
class ParentClass (ClassChanger, ManagedBleakDevice):

    def __init__(self):
        super(ParentClass, self).__init__()


class VariantA (ParentClass):

    def __init__(self):
        super(VariantA, self).__init__()
        self.local_str = 'VariantA'

    async def _leave_class(self):
        delattr(self, 'local_str')

    async def _adopt_class(self):
        self.local_str = 'VariantA'

    def get_local(self):
        return self.local_str

    def from_a(self):
        return 'from_a exists'


class VariantA2 (VariantA):

    def __init__(self):
        super(VariantA2, self).__init__()
        self.local_str = 'VariantA2'

    async def _leave_class(self):
        delattr(self, 'local_str')

    async def _adopt_class(self):
        self.local_str = 'VariantA2'

    def get_local(self):
        return self.local_str

    def from_a2(self):
        return 'from_a2 exists'


class VariantB (ParentClass):

    def __init__(self):
        super(VariantB, self).__init__()
        self.local_str = 'VariantB'

    async def _leave_class(self):
        delattr(self, 'local_str')

    async def _adopt_class(self):
        self.local_str = 'VariantB'

    def from_b(self):
        return 'from_b exists'


def duck_check(obj, isa: type):
    assert isinstance(obj, isa)
    if isa != ParentClass:
        duck_check(obj, ParentClass)

    if isa == ParentClass:
        assert     hasattr(obj, '_class_change_lock')

    elif isa == VariantA:
        obj: VariantA
        assert obj.local_str == 'VariantA'
        assert     hasattr(obj, 'get_local')
        assert     hasattr(obj, 'from_a')
        assert not hasattr(obj, 'from_a2')
        assert not hasattr(obj, 'from_b')
        assert obj.get_local() == 'VariantA'
        assert obj.from_a() == 'from_a exists'

    elif isa == VariantA2:
        obj: VariantA2
        assert obj.local_str == 'VariantA2'
        assert     hasattr(obj, 'get_local')
        assert     hasattr(obj, 'from_a')
        assert     hasattr(obj, 'from_a2')
        assert not hasattr(obj, 'from_b')
        assert obj.from_a() == 'from_a exists'
        assert obj.from_a2() == 'from_a2 exists'
        assert obj.get_local() == 'VariantA2'

    elif isa == VariantB:
        obj: VariantB
        assert obj.local_str == 'VariantB'
        assert not hasattr(obj, 'get_local')
        assert not hasattr(obj, 'from_a')
        assert not hasattr(obj, 'from_a2')
        assert     hasattr(obj, 'from_b')
        assert obj.from_b() == 'from_b exists'

    else:
        assert False, f"Unknown type to check against, {isa}"


@pytest.mark.asyncio
async def test_class_changer():

    p = ParentClass()
    assert p._class_changer_generic_class == ParentClass
    a = VariantA()
    a2 = VariantA2()
    b = VariantB()
    assert a._class_changer_generic_class == ParentClass
    assert a2._class_changer_generic_class == ParentClass
    assert b._class_changer_generic_class == ParentClass

    duck_check(a, VariantA)
    duck_check(a2, VariantA2)
    duck_check(b, VariantB)

    await a._change_class(VariantB)
    duck_check(a, VariantB)
