"""Synthetic second-factor checks; no live account or network."""
import ast,io,json,os,time,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QHBoxLayout,QLabel,QLineEdit,QCheckBox,QPushButton
from PySide6.QtTest import QTest
from nexus_launcher.nexus_account import NexusAccountClient,AccountError,SessionRejected
from nexus_launcher.themed_dialog import NexusDialog
# Execute the actual two form class bodies without importing the unrelated Studio
# Markdown/editor stack or starting the application shell.
namespace={name:value for name,value in globals().copy().items()}
for source_name,class_name in [('nexus_launcher/modern_main.py','LoginDialog'),('nexus_launcher/nexus_platform/next_shell.py','NexusLogin')]:
 tree=ast.parse(Path(source_name).read_text(encoding='utf-8'))
 body=next(node for node in tree.body if isinstance(node,ast.ClassDef) and node.name==class_name)
 exec(compile(ast.Module(body=[body],type_ignores=[]),source_name,'exec'),namespace)
NexusLogin=namespace['NexusLogin']
from nexus_launcher.nexus_platform.auth_state import AuthState
from nexus_launcher.nexus_platform.presentation_style import stylesheet
class TwoFactorTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])
 def test_client_factor_and_session_boundary(self):
  client=NexusAccountClient('https://example.invalid')
  response={'token':'a'*64,'user':{'minecraftNick':'Fixture','email':'fixture@example.invalid'}}
  with patch.object(client,'_device_id',return_value='fixture'),patch.object(client,'_request',return_value=(response,None)) as request,patch('nexus_launcher.nexus_account.keyring.set_password') as save:
   client.login('Fixture','fixture-password',totp_code='123456')
   self.assertEqual(request.call_args.kwargs['payload']['totpCode'],'123456');save.assert_called_once()
  with patch.object(client,'_request') as request:
   for code in ['１２３４５６','12345',' 123456']:
    with self.assertRaises(AccountError):client.login('Fixture','fixture',totp_code=code)
   with self.assertRaises(AccountError):client.login('Fixture','fixture',totp_code='123456',recovery_code='ab'*16)
   request.assert_not_called()
  with patch.object(client,'_request',return_value=({'twoFactorRequired':True},None)),patch('nexus_launcher.nexus_account.keyring.set_password') as save:
   with self.assertRaises(AccountError):client.login('Fixture','fixture')
   save.assert_not_called()
 def test_http_challenge_is_not_a_revoked_session(self):
  client=NexusAccountClient('https://example.invalid')
  error=urllib.error.HTTPError('https://example.invalid/login',401,'fixture',{},io.BytesIO(json.dumps({'twoFactorRequired':True,'error':'Введите код'}).encode()))
  with patch('nexus_launcher.nexus_account.open_https',side_effect=error):
   with self.assertRaises(AccountError) as caught:client._request('/api/launcher/auth/login',method='POST',payload={})
   self.assertEqual(caught.exception.code,'MFA_REQUIRED');self.assertNotIsInstance(caught.exception,SessionRejected)
 def test_native_factor_selection_and_clearing(self):
  parent=QWidget();dialog=NexusLogin(parent);dialog.setStyleSheet(stylesheet());dialog.show()
  dialog.mfa_code.setText('123456');self.assertEqual(dialog.second_factor(),('123456',''));self.assertEqual(dialog.mfa_code.text(),'')
  dialog.mfa_recovery.setChecked(True);dialog.mfa_code.setText('abcdef01-'*3+'abcdef01')
  self.assertEqual(dialog.second_factor(),('', 'abcdef01-'*3+'abcdef01'))
  QTest.qWait(100)
  if os.environ.get('NEXUS_TWO_FACTOR_SCREENSHOT'):self.assertTrue(dialog.grab().save(os.environ['NEXUS_TWO_FACTOR_SCREENSHOT']))
  dialog.password.setText('synthetic');dialog.mfa_code.setText('123456');dialog.reject()
  self.assertEqual(dialog.password.text(),'');self.assertEqual(dialog.mfa_code.text(),'');parent.close()
 def test_auth_owner_forwards_factor_without_leaking_error(self):
  calls=[]
  class Client:
   def login(self,*args,**kwargs):calls.append(kwargs);raise AccountError('private detail',code='MFA_REQUIRED')
  auth=AuthState(Client());auth.run('login','Fixture','synthetic',totp_code='123456')
  end=time.monotonic()+10
  while auth.busy and time.monotonic()<end:self.app.processEvents();time.sleep(.01)
  self.assertFalse(auth.busy);self.assertEqual(auth.connection,'MFA_REQUIRED');self.assertIsNone(auth.user)
  self.assertNotIn('private',auth.message);self.assertEqual(calls,[{'totp_code':'123456'}])
if __name__=='__main__':unittest.main()
