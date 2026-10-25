from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from chat.testing import isolated_prefix


class LegacyAccountMigrationTests(TransactionTestCase):
    def test_customuser_rows_become_auth_users(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('main', '0003_delete_room')])
        CustomUser = executor.loader.project_state([('main', '0003_delete_room')]).apps.get_model('main', 'CustomUser')
        CustomUser.objects.create(username='legacy', email='legacy@example.com', password='pbkdf2_sha256$x$y$z')
        CustomUser.objects.create(username='taken', email='t@example.com', password='other')
        User.objects.create(username='taken', password='keep-me')
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        self.assertEqual(User.objects.get(username='legacy').password, 'pbkdf2_sha256$x$y$z')
        self.assertEqual(User.objects.get(username='taken').password, 'keep-me')
        self.assertNotIn('main_customuser', connection.introspection.table_names())


class AccountTests(TestCase):
    def setUp(self):
        isolated_prefix(self)

    def test_signup_validates_password_and_duplicate_username(self):
        data = {'username': 'tester', 'email': 'test@example.com',
                'password1': 'A-long-new-password-789!', 'password2': 'A-long-new-password-789!'}
        self.assertRedirects(self.client.post('/signup/', data), '/login/')
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(self.client.post('/signup/', data).status_code, 200)
        self.assertEqual(User.objects.count(), 1)
        data.update(username='other', password1='123', password2='123')
        self.assertEqual(self.client.post('/signup/', data).status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_login_and_post_only_logout(self):
        User.objects.create_user('tester', password='test-password-123!')
        self.assertRedirects(self.client.post('/login/', {'username': 'tester', 'password': 'test-password-123!'}), '/home/')
        self.assertEqual(self.client.get('/logout/').status_code, 405)
        self.assertRedirects(self.client.post('/logout/'), '/', target_status_code=302)
        self.assertEqual(self.client.get('/home/').status_code, 302)
