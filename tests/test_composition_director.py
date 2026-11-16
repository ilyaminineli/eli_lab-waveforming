from engine.visual.composition_director import create_auto_composition, vary_composition


def test_auto_composition_assigns_independent_source_channels():
    names = [
        "GEOMETRIC PLATE", "GEOMETRIC FIELD", "AXONOMETRIC FIELD",
        "POLYHEDRAL FIELD", "PHASE ORBIT", "PHASE LATTICE",
        "MOBIUS FIELD", "SPECTRAL TOPOGRAPHY", "PHYLLOTAXIS",
    ]
    source_ids = ["src-a", "src-b", "src-c", "src-d"]
    layers = create_auto_composition(names, source_ids, seed=1234)

    assert len(layers) == len(source_ids) + 1
    assert layers[0].generator == "GEOMETRIC PLATE"
    assert [layer.source_id for layer in layers[1:]] == source_ids
    assert [layer.palette_index for layer in layers[1:]] == list(range(len(source_ids)))
    assert all(layer.palette_mode == "MUTED PRIDE" for layer in layers[1:])


def test_variation_keeps_layer_count_and_source_routing():
    names = [
        "GEOMETRIC PLATE", "GEOMETRIC FIELD", "AXONOMETRIC FIELD",
        "POLYHEDRAL FIELD", "PHASE ORBIT", "PHASE LATTICE",
        "MOBIUS FIELD", "SPECTRAL TOPOGRAPHY", "PHYLLOTAXIS",
    ]
    layers = create_auto_composition(names, ["src-a", "src-b", "src-c"], seed=2)
    routing_before = [layer.source_id for layer in layers]
    varied = vary_composition(layers, names, seed=999)

    assert len(varied) == len(layers)
    assert [layer.source_id for layer in varied] == routing_before
    assert all(0.0 <= layer.opacity <= 1.0 for layer in varied)
    assert all(0.1 <= layer.scale <= 3.0 for layer in varied)
