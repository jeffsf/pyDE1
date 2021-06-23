"""
This class derived from that of Guido van Rossum available at
https://www.python.org/download/releases/2.2.3/descrintro/

As such, it appears from
https://docs.python.org/3/license.html#terms-and-conditions-for-accessing-or-otherwise-using-python
to be available under at least
https://docs.python.org/3/license.html#psf-license, retrieved from that URL
at the time this was originally added (2021-06-22)

1. This LICENSE AGREEMENT is between the Python Software Foundation ("PSF"), and
   the Individual or Organization ("Licensee") accessing and otherwise using Python
   3.9.5 software in source or binary form and its associated documentation.

2. Subject to the terms and conditions of this License Agreement, PSF hereby
   grants Licensee a nonexclusive, royalty-free, world-wide license to reproduce,
   analyze, test, perform and/or display publicly, prepare derivative works,
   distribute, and otherwise use Python 3.9.5 alone or in any derivative
   version, provided, however, that PSF's License Agreement and PSF's notice of
   copyright, i.e., "Copyright © 2001-2021 Python Software Foundation; All Rights
   Reserved" are retained in Python 3.9.5 alone or in any derivative version
   prepared by Licensee.

3. In the event Licensee prepares a derivative work that is based on or
   incorporates Python 3.9.5 or any part thereof, and wants to make the
   derivative work available to others as provided herein, then Licensee hereby
   agrees to include in any such work a brief summary of the changes made to Python
   3.9.5.

4. PSF is making Python 3.9.5 available to Licensee on an "AS IS" basis.
   PSF MAKES NO REPRESENTATIONS OR WARRANTIES, EXPRESS OR IMPLIED.  BY WAY OF
   EXAMPLE, BUT NOT LIMITATION, PSF MAKES NO AND DISCLAIMS ANY REPRESENTATION OR
   WARRANTY OF MERCHANTABILITY OR FITNESS FOR ANY PARTICULAR PURPOSE OR THAT THE
   USE OF PYTHON 3.9.5 WILL NOT INFRINGE ANY THIRD PARTY RIGHTS.

5. PSF SHALL NOT BE LIABLE TO LICENSEE OR ANY OTHER USERS OF PYTHON 3.9.5
   FOR ANY INCIDENTAL, SPECIAL, OR CONSEQUENTIAL DAMAGES OR LOSS AS A RESULT OF
   MODIFYING, DISTRIBUTING, OR OTHERWISE USING PYTHON 3.9.5, OR ANY DERIVATIVE
   THEREOF, EVEN IF ADVISED OF THE POSSIBILITY THEREOF.

6. This License Agreement will automatically terminate upon a material breach of
   its terms and conditions.

7. Nothing in this License Agreement shall be deemed to create any relationship
   of agency, partnership, or joint venture between PSF and Licensee.  This License
   Agreement does not grant permission to use PSF trademarks or trade name in a
   trademark sense to endorse or promote products or services of Licensee, or any
   third party.

8. By copying, installing or otherwise using Python 3.9.5, Licensee agrees
   to be bound by the terms and conditions of this License Agreement.
"""


class Singleton:

    def __new__(cls, *args, **kwds):
        it = cls.__dict__.get("__it__")
        if it is not None:
            return it
        cls.__it__ = it = object.__new__(cls)
        it._singleton_init(*args, **kwds)
        return it

    def _singleton_init(self, *args, **kwds):
        pass

# NB: Original "init" changed to "_singleton_init" for clarity in subclasses

# To create a singleton class, you subclass from Singleton;
# each subclass will have a single instance,
# no matter how many times its constructor is called.
# To further initialize the subclass instance,
# subclasses should override 'init' instead of __init__
# - the __init__ method is called each time the constructor is called.
# For example:
#
# >>> class MySingleton(Singleton):
# ...     def init(self):
# ...         print "calling init"
# ...     def __init__(self):
# ...         print "calling __init__"
# ...
# >>> x = MySingleton()
# calling init
# calling __init__
# >>> assert x.__class__ is MySingleton
# >>> y = MySingleton()
# calling __init__
# >>> assert x is y
# >>>