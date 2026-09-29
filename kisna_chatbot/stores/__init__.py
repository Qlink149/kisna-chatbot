"""Bookable KISNA stores for the Store Visit Flow.

``model`` normalises raw records (kisna.com list, dashboard CSV) into one
shape, ``repo`` owns the Mongo ``stores`` collection and the CSV import, and
``cache`` is the short-TTL read layer the Flow endpoint calls on every tap.
"""
