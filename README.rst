FreeCAD lumberjack workbench
============================

Making FreeCAD convenient for woodworkers.

The lumberjack workbench was written in order to streamline designing and constructing furniture.
It has been written specifically for the Assembly3 Workbench and the socalled Linkstage Fork of FreeCAD.

It currently offers (only) two features: creating basic parts, pre-wrapped in an assembly container and preliminary calculation of a cutlist.



Future Features
---------------

* create part should label the created part as such
* offer option to create single or multiple links inside the currently active assembly upon creation of the part
* Reasonable duplicate of a given part (specifically a component inside the Componentsfolder - the UI should be to select a link of the component in the assembly and then initiate "duplicate" command), replacing an existing item (a.k.a. "oops, i need this to be different, after all...")
	* find the original of the link
	* figure out, which API is used (record copy from GUI), then figure out which subset is good
	* offer to rename the part immediately (thus allowing to rename all of its subcomponents (Elements, Constraints))
		* helper function to recursively rename elements (probably best bottom up, since we are renaming on the way)
	* move the duplicate out of the way by moving it so far UP that the vertical distance between their bounding box is as large as the smallest side of its bounding box
	* helper method to replace an existing assembly with another one (we know / need to figure out the relationship between the old elements and the new one and then replace the any old elements that are part of any constraint with their new copy)

* probably should keep the Components layout programmatically visually organized by placing new components in relation to existing ones on the same plane (i.e. along the X axis) and variations of them at they x-coordinate but along the y axis

* offer hotkey to show/hide the components specifically

* helper method to rename a component (renames its parts and bodies accordingly)