"""Observer: sprite loader, the read-only map window and the full screen."""

from ai_island.observer.observer import Observer
from ai_island.observer.sprites import load_sprites
from ai_island.observer.viewer import Viewer, light_alpha, slide_position

__all__ = ["Observer", "Viewer", "light_alpha", "load_sprites", "slide_position"]
