"""Export a project's knowledge graph as Brick Turtle and check it with SHACL (work package W2).

    from projectmodel.export import export_project, load_export, validate
    ex = export_project(store, "alpha/names_paths", km)           # confirmed rows only
    ex = export_project(store, project, km, include_proposed=True)  # plus the proposed ones
    ex.write("alpha.ttl"); load_export("alpha.ttl")                 # round trip: same node and edge counts
    report = validate(ex, km)                                        # Brick's shapes + knowledge_model/shapes/*.ttl

Data flows one way: the export reads the store and writes files; nothing is written back.
"""
from .brick import PM, Export, class_uri, export_project, load_export, node_uri, relation_uri
from .shacl import SHAPES_DIR, load_shapes, validate

__all__ = ["PM", "SHAPES_DIR", "Export", "class_uri", "export_project", "load_export", "load_shapes", "node_uri",
           "relation_uri", "validate"]
