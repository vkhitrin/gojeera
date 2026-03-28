from __future__ import annotations

from dataclasses import replace

from textual.binding import Binding
from textual.command import DiscoveryHit, Hit, Hits, Provider

COMMAND_PALETTE_BINDING_ID_PREFIX = 'command-palette:'


def register_binding_in_command_palette(
    binding: Binding,
    *,
    command_id: str | None = None,
) -> Binding:
    """Mark a footer binding for explicit command palette registration."""

    binding_id = command_id or binding.id or binding.action
    return replace(binding, id=f'{COMMAND_PALETTE_BINDING_ID_PREFIX}{binding_id}')


class RegisteredBindingCommandProvider(Provider):
    """Expose explicitly-registered active bindings in the command palette."""

    @staticmethod
    def _get_help_text(active_binding) -> str:
        return active_binding.tooltip

    def _iter_bindings(self):
        for active_binding in self.screen.active_bindings.values():
            binding = active_binding.binding
            if not active_binding.enabled:
                continue
            if not binding.description:
                continue
            if not binding.id or not binding.id.startswith(COMMAND_PALETTE_BINDING_ID_PREFIX):
                continue
            yield active_binding

    async def discover(self) -> Hits:
        for active_binding in self._iter_bindings():
            binding = active_binding.binding
            yield DiscoveryHit(
                binding.description,
                self._make_callback(binding.action, active_binding.node),
                help=self._get_help_text(active_binding),
            )

    async def search(self, query: str) -> Hits:
        matcher = self.matcher(query)
        for active_binding in self._iter_bindings():
            binding = active_binding.binding
            score = matcher.match(binding.description)
            if score > 0:
                yield Hit(
                    score,
                    matcher.highlight(binding.description),
                    self._make_callback(binding.action, active_binding.node),
                    help=self._get_help_text(active_binding),
                )

    def _make_callback(self, action: str, namespace):
        async def run_command() -> None:
            await self.app.run_action(action, namespace)

        return run_command
