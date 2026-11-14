"""Online installer; explicit UAC is restricted to preparing a new directory."""
import os
from pathlib import Path
import sys

def main():
 if os.name!='nt' or not getattr(sys,'frozen',False):raise RuntimeError('Packaged Windows installer required')
 import nexus_launcher.build_channel as channel
 channel.PUBLIC_PREVIEW_BUILD=True
 from nexus_launcher.online_installation import install,installed_root,validate_destination,installation_details
 root=installed_root(Path(sys.executable))
 if root is not None:
  from nexus_launcher.public_bootstrap_main import main as launch
  return launch(installation_root=root)
 from PySide6.QtCore import QThread,Signal,QTimer
 from PySide6.QtGui import QIcon
 from PySide6.QtWidgets import QApplication,QFileDialog,QLabel,QLineEdit,QPushButton,QProgressBar,QVBoxLayout,QHBoxLayout,QMessageBox
 from nexus_launcher.themed_dialog import NexusDialog
 from nexus_launcher.nexus_platform.presentation_style import stylesheet
 from nexus_launcher.nexus_platform.theme_tokens import TOKENS
 from nexus_launcher.github_updates import GitHubPackageTransport
 from nexus_launcher.public_update_identity import FEED
 from nexus_launcher.windows_bootstrap_process import WindowsLaunchLease
 from nexus_launcher.connection_diagnostics import transport_failure
 import json
 class Worker(QThread):
  progress=Signal(object)
  finished_install=Signal(object)
  def __init__(self,directory,parent):super().__init__(parent);self.directory=directory
  def run(self):
   phase='CHECKING'
   def emit(name,done,total):
    nonlocal phase
    phase=name;self.progress.emit((name,done,total))
   try:
    selected,_=validate_destination(self.directory,sys.executable)
    with WindowsLaunchLease(selected):
     target=install(selected,sys.executable,GitHubPackageTransport(FEED,timeout=20),emit)
     details=installation_details(target)
    self.finished_install.emit((details,None))
   except Exception as error:
    if isinstance(error,PermissionError):
     self.finished_install.emit((None,'INSTALL_PERMISSION_REQUIRED'));return
    category=transport_failure(error)['category']
    known={'INSTALL_DIRECTORY_NOT_EMPTY':'Выберите пустую папку. Существующие файлы не изменялись.','INSTALL_ALREADY_OWNED':'В папке находится другая установка. Выберите новую пустую папку.','INSTALL_PATH_TOO_LONG':'Выберите более короткий путь установки.','INSTALL_EXECUTABLE_CONFLICT':'В папке уже есть другой NEXUS.exe. Он не заменён.'}
    detail=known.get(str(error))
    if not detail:
     detail={'TLS_CERTIFICATE':'Не удалось проверить HTTPS-сертификат. Проверка безопасности не отключалась.','DNS':'Не удалось найти сервер загрузки.','TIMEOUT':'Истекло время ожидания. Проверьте подключение и повторите.'}.get(category)
    if not detail:detail='Не удалось завершить установку. Код: '+phase+'_'+('IO' if isinstance(error,OSError) else 'REJECTED' if isinstance(error,ValueError) else 'FAILED')+'.'
    self.finished_install.emit((None,detail))
 class Window(NexusDialog):
  def __init__(self):
   from nexus_launcher.public_update_identity import CHANNEL
   super().__init__();self.worker=None;self.target=None;self.details=None;self.completion=None;self.shortcut_created=False;self.needs_permissions=False;self.permission_request=None
   self.setWindowTitle('Установка NEXUS Testers' if CHANNEL=='beta' else 'Установка NEXUS Launcher')
   from nexus_launcher.installer_presentation import build_installer
   build_installer(self, CHANNEL=='beta')
   self.licenses.clicked.connect(lambda:os.startfile(str(Path(sys._MEIPASS)/'third-party-notices')))
  def browse(self):
   value=QFileDialog.getExistingDirectory(self,'Выберите папку установки',self.path.text())
   if value:self.path.setText(str(Path(value)))
  def start(self):
   if self.worker or self.permission_request:return
   self.needs_permissions=False
   self.go.setEnabled(False);self.choose.setEnabled(False);self.path.setEnabled(False);self.title_bar.close_button.setEnabled(False)
   self.worker=Worker(Path(self.path.text()),self);self.worker.progress.connect(self.progress);self.worker.finished_install.connect(self.result);self.worker.finished.connect(self.done_worker);self.worker.start()
  def progress(self,value):
   phase,done,total=value
   self.status.setText({'CHECKING':'Проверяем выпуск…','DOWNLOADING':'Скачиваем полный лаунчер…','VERIFYING':'Проверяем и распаковываем файлы…','COMPLETE':'Лаунчер установлен.'}[phase])
   self.bar.setRange(0,100 if total else 0)
   self.percent.setText(f'{min(99,done*100//total)}%' if total else '…')
   if total:self.bar.setValue(min(99,done*100//total))
   if hasattr(self,'transfer_detail'):
    self.transfer_detail.setText(f'{done/(1024*1024):.1f} / {total/(1024*1024):.1f} МБ' if total else 'Проверяем файлы. Это может занять несколько минут.' if phase=='VERIFYING' else 'Ожидаем данные выпуска…')
    active={'CHECKING':0,'DOWNLOADING':1,'VERIFYING':2,'COMPLETE':3}[phase]
    for index,label in enumerate(self.phase_labels):label.setStyleSheet('color:#83c9ff;font-weight:650;' if index<=active else 'color:#8193aa;')

  def result(self,result):
   details,error=result;self.needs_permissions=error=='INSTALL_PERMISSION_REQUIRED';self.details=details;self.target=details.executable if details else None;self.status.setText('Нет прав записи в выбранную папку.' if self.needs_permissions else error or 'Установка завершена. Можно запускать NEXUS.');self.bar.setRange(0,100);self.bar.setValue(100 if details else 0);self.percent.setText('100%' if details else 'Установка не завершена')
  def done_worker(self):
   self.worker.deleteLater();self.worker=None;self.title_bar.close_button.setEnabled(True)
   self.go.setVisible(self.target is None);self.go.setEnabled(True);self.choose.setEnabled(self.target is None);self.path.setEnabled(self.target is None)
   self.open.setVisible(self.target is not None);self.launch.setVisible(self.target is not None)
   if self.target is not None:self.show_completion()
   elif self.needs_permissions:QTimer.singleShot(0,self.ask_permissions)
  def ask_permissions(self):
   from nexus_launcher.installer_permissions import PermissionRequest,current_sid,validate_request
   directory=Path(self.path.text())
   try:validate_request(directory,current_sid())
   except Exception:
    self.status.setText('Для запроса Windows выберите новую папку внутри существующей. Права существующих папок не изменяются.');return
   answer=QMessageBox.question(self,'Разрешить создание папки?',f'Создать папку {directory} и разрешить вашему пользователю запись в неё? Windows запросит подтверждение администратора. Лаунчер и игра не будут запускаться от администратора.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)
   if answer!=QMessageBox.Yes:return
   try:self.permission_request=PermissionRequest(directory,int(self.winId()))
   except OSError as error:
    self.status.setText('Запрос Windows отменён. Можно выбрать другую папку.' if getattr(error,'winerror',None)==1223 else 'Не удалось запросить создание папки. Выберите доступную папку.');return
   self.go.setEnabled(False);self.choose.setEnabled(False);self.path.setEnabled(False);self.title_bar.close_button.setEnabled(False)
   self.status.setText('Ожидаем подтверждения Windows и создания папки…')
   self.permission_timer=QTimer(self);self.permission_timer.timeout.connect(self.poll_permissions);self.permission_timer.start(250)
  def poll_permissions(self):
   try:code=self.permission_request.poll()
   except OSError:
    self.permission_timer.stop();self.status.setText('Не удалось подтвердить завершение запроса Windows. Закройте установщик после завершения системного запроса.');return
   if code is None:return
   self.permission_timer.stop();self.permission_request=None;self.title_bar.close_button.setEnabled(True);self.go.setEnabled(True);self.choose.setEnabled(True);self.path.setEnabled(True)
   if code==0:self.start()
   else:self.status.setText('Папка не подготовлена. Выберите другую новую папку; установка не продолжалась.')
  def show_completion(self):
   from nexus_launcher.installer_completion import CompletionWindow
   self.completion=CompletionWindow(self.details)
   self.completion.launch_requested.connect(lambda shortcut:self.complete_install(True,shortcut))
   self.completion.finish_requested.connect(self.complete_install)
   self.completion.folder_requested.connect(self.open_install_folder)
   self.completion.licenses_requested.connect(self.licenses.click)
   self.completion.finished.connect(self.accept)
   available=app.primaryScreen().availableGeometry()
   self.completion.resize(min(1040,int(available.width()*.94)),min(800,int(available.height()*.94)))
   self.completion.show();self.hide()
  def open_install_folder(self):
   try:os.startfile(str(self.target.parent))
   except OSError:self.completion.show_error('Не удалось открыть папку. Скопируйте путь из блока установки.')
  def complete_install(self,launch,shortcut):
   if not self.target or not self.completion:return
   import subprocess
   self.completion.set_busy(True)
   phase='VERIFY'
   try:
    if installed_root(self.target)!=self.target.parent:raise ValueError('INSTALL_RECEIPT_INVALID')
    if shortcut and not self.shortcut_created:
     phase='SHORTCUT'
     from nexus_launcher.windows_shortcut import create_shortcut,desktop_directory
     create_shortcut(self.target,desktop_directory());self.shortcut_created=True
    if launch:
     phase='LAUNCH'
     subprocess.Popen([str(self.target)],cwd=str(self.target.parent),close_fds=True)
    self.completion.accept()
   except Exception:
    message={'VERIFY':'Не удалось подтвердить установленный NEXUS. Файлы не запускались.','SHORTCUT':'Не удалось создать ярлык. Снимите флажок, чтобы завершить без него.','LAUNCH':'Не удалось запустить NEXUS. Откройте папку установки и повторите запуск.'}[phase]
    self.completion.show_error(message);self.completion.set_busy(False)
  def run_launcher(self):
   if not self.target:return
   import subprocess
   try:
    if installed_root(self.target)!=self.target.parent:raise ValueError('INSTALL_RECEIPT_INVALID')
    self.launch.setEnabled(False)
    subprocess.Popen([str(self.target)],cwd=str(self.target.parent),close_fds=True)
    self.accept()
   except Exception:self.status.setText('Не удалось запустить NEXUS. Откройте папку установки и повторите запуск.');self.launch.setEnabled(True)
  def reject(self):
   if self.worker is None and self.permission_request is None:super().reject()
  def closeEvent(self,event):
   if self.worker or self.permission_request:event.ignore()
   else:super().closeEvent(event)
 app=QApplication(sys.argv);app.setApplicationName('NEXUS Setup');app.setWindowIcon(QIcon(str(Path(sys._MEIPASS)/'assets/icon.ico')))
 window=Window();window.show()
 if '--self-test-report' in sys.argv:
  report=Path(sys.argv[sys.argv.index('--self-test-report')+1]);window.grab().save(str(report.with_suffix('.png')));
  with report.open('x',encoding='utf-8') as stream:json.dump({'schema':1,'window_visible':window.isVisible(),'download_started':window.worker is not None,'elevation_requested':False},stream)
  QTimer.singleShot(50,app.quit)
 return app.exec()

if __name__=='__main__':
 try:sys.exit(main())
 except Exception:
  from PySide6.QtWidgets import QApplication,QLabel,QPushButton,QVBoxLayout
  from nexus_launcher.themed_dialog import NexusDialog
  from nexus_launcher.nexus_platform.presentation_style import stylesheet
  from nexus_launcher.nexus_platform.theme_tokens import TOKENS
  app=QApplication.instance() or QApplication([]);dialog=NexusDialog();dialog.setWindowTitle('NEXUS — запуск недоступен');dialog.setStyleSheet(stylesheet()+f"QDialog {{ background:{TOKENS['background']}; }}")
  box=QVBoxLayout(dialog);message=QLabel('Не удалось подтвердить установку. Закройте запущенный NEXUS и проверьте целостность папки установки. Защита Windows не отключалась.');message.setWordWrap(True);box.addWidget(message);close=QPushButton('Закрыть');close.clicked.connect(dialog.accept);box.addWidget(close);dialog.exec();sys.exit(1)
