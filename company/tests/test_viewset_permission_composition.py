"""Quota checks must COMPOSE with the class permissions, never replace them.

`CompanyNestedViewSet` defends every nested endpoint with
`[IsSuperUser | (ReadOnlyForViewers & AuthPermission)]` — that pair is what enforces company
MEMBERSHIP and the CA/FM write ROLE.

Both `EstablishmentViewSet` and `ParcelViewSet` overrode `get_permissions()` to add a
subscription-quota check, and did it by RETURNING A NEW LIST. That silently dropped the class
default. On `EstablishmentViewSet` the effect was worst, because
`HasEstablishmentCreationPermission.has_permission` returns `True` for every non-POST method: on
PUT/PATCH the only surviving check was `IsAuthenticated`, so a Viewer-role member could edit a
farm.

These tests assert the SHAPE of the returned permission list rather than driving HTTP, so they
stay meaningful regardless of how the quota rules themselves evolve.
"""

from django.test import TestCase


class EstablishmentPermissionCompositionTests(TestCase):
    def _permissions_for(self, action):
        from company.views import EstablishmentViewSet

        view = EstablishmentViewSet()
        view.action = action
        view.company = None
        view.kwargs = {}
        return view.get_permissions()

    def test_class_default_survives_on_create(self):
        from backend.permissions import CompanyNestedViewSet

        names = {type(p).__name__ for p in self._permissions_for("create")}
        default_names = {type(p()).__name__ for p in CompanyNestedViewSet.permission_classes}
        self.assertTrue(
            default_names <= names,
            f"class permissions dropped on create: expected {default_names} within {names}",
        )

    def test_class_default_survives_on_update(self):
        # The regression that let a Viewer PATCH a farm.
        from backend.permissions import CompanyNestedViewSet

        default_names = {type(p()).__name__ for p in CompanyNestedViewSet.permission_classes}
        for action in ("update", "partial_update"):
            with self.subTest(action=action):
                names = {type(p).__name__ for p in self._permissions_for(action)}
                self.assertTrue(
                    default_names <= names,
                    f"class permissions dropped on {action}: expected {default_names} within {names}",
                )

    def test_quota_check_is_still_applied(self):
        names = {type(p).__name__ for p in self._permissions_for("create")}
        self.assertIn("HasEstablishmentCreationPermission", names)

    def test_destroy_remains_company_admin_only(self):
        names = {type(p).__name__ for p in self._permissions_for("destroy")}
        self.assertEqual(names, {"IsCompanyAdmin"})

    def test_bare_isauthenticated_is_not_the_only_gate(self):
        # A list of exactly [IsAuthenticated, <quota>] is the broken shape: the quota class waves
        # through every non-POST, leaving "is logged in" as the whole defence.
        for action in ("update", "partial_update"):
            with self.subTest(action=action):
                names = [type(p).__name__ for p in self._permissions_for(action)]
                self.assertNotEqual(sorted(names), ["HasEstablishmentCreationPermission", "IsAuthenticated"])


class ParcelPermissionCompositionTests(TestCase):
    def _permissions_for(self, action):
        from product.views import ParcelViewSet

        view = ParcelViewSet()
        view.action = action
        view.company = None
        view.kwargs = {}
        return view.get_permissions()

    def test_class_default_survives_on_create(self):
        from backend.permissions import CompanyNestedViewSet

        names = {type(p).__name__ for p in self._permissions_for("create")}
        default_names = {type(p()).__name__ for p in CompanyNestedViewSet.permission_classes}
        self.assertTrue(
            default_names <= names,
            f"class permissions dropped on create: expected {default_names} within {names}",
        )

    def test_quota_check_is_still_applied(self):
        names = {type(p).__name__ for p in self._permissions_for("create")}
        self.assertIn("HasParcelCreationPermission", names)

    def test_non_create_actions_use_the_class_default_unchanged(self):
        from backend.permissions import CompanyNestedViewSet

        names = [type(p).__name__ for p in self._permissions_for("update")]
        expected = [type(p()).__name__ for p in CompanyNestedViewSet.permission_classes]
        self.assertEqual(names, expected)
