from django.test import TestCase
from django.contrib.auth.models import User


class AccountTests(TestCase):
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
