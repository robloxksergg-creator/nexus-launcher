"""One-file online installer and installed bootstrap entry point. No elevation."""
import os
from pathlib import Path
import sys

def main():
 if os.name!='nt' or not getattr(sys,'frozen',False):raise RuntimeError('Packaged Windows installer required')
 import nexus_launcher.build_channel as channel
 channel.PUBLIC_PREVIEW_BUILD=True
 from nexus_launcher.online_installation import install,installed_root,validate_destination
 root=installed_root(Path(sys.executable))
 if root is not None:
  from nexus_launcher.public_bootstrap_main import main as launch
  return launch(installation_root=root)
 from PySide6.QtCore import QThread,Signal,QTimer
 from PySide6.QtGui import QIcon
 from PySide6.QtWidgets import QApplication,QFileDialog,QLabel,QLineEdit,QPushButton,QProgressBar,QVBoxLayout,QHBoxLayout
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
    with WindowsLaunchLease(selected):target=install(selected,sys.executable,GitHubPackageTransport(FEED,timeout=20),emit)
    self.finished_install.emit((str(target),None))
   except Exception as error:
    category=transport_failure(error)['category']
    known={'INSTALL_DIRECTORY_NOT_EMPTY':'Выберите пустую папку. Существующие файлы не изменялись.','INSTALL_ALREADY_OWNED':'В папке находится другая установка. Выберите новую пустую папку.','INSTALL_PATH_TOO_LONG':'Выберите более короткий путь установки.','INSTALL_EXECUTABLE_CONFLICT':'В папке уже есть другой NEXUS.exe. Он не заменён.'}
    detail=known.get(str(error))
    if not detail:
     detail={'TLS_CERTIFICATE':'Не удалось проверить HTTPS-сертификат. Проверка безопасности не отключалась.','DNS':'Не удалось найти сервер загрузки.','TIMEOUT':'Истекло время ожидания. Проверьте подключение и повторите.'}.get(category)
    if not detail:detail='Не удалось завершить установку. Код: '+phase+'_'+('IO' if isinstance(error,OSError) else 'REJECTED' if isinstance(error,ValueError) else 'FAILED')+'.'
    self.finished_install.emit((None,detail))
 class Window(NexusDialog):
  def __init__(self):
   super().__init__();self.worker=None;self.target=None
   self.setWindowTitle('Установка NEXUS Launcher');self.setMinimumWidth(520);self.setStyleSheet(stylesheet()+f"QDialog {{ background:{TOKENS['background']}; }}")
   box=QVBoxLayout(self);box.setContentsMargins(28,24,28,24);box.setSpacing(16)
   title=QLabel('NEXUS Launcher');title.setStyleSheet('font-size:28px;font-weight:700');box.addWidget(title)
   info=QLabel('Выберите папку. Установщик скачает полный лаунчер с GitHub, проверит подпись и файлы. Права администратора не требуются.');info.setWordWrap(True);box.addWidget(info)
   box.addWidget(QLabel('Папка установки и данных сборок'))
   row=QHBoxLayout();self.path=QLineEdit(str(Path(os.environ['LOCALAPPDATA'])/'Programs'/'NEXUS Launcher'));self.path.setAccessibleName('Папка установки');self.choose=QPushButton('Выбрать…');self.choose.clicked.connect(self.browse);row.addWidget(self.path);row.addWidget(self.choose);box.addLayout(row)
   note=QLabel('Старые сборки не переносятся автоматически. Место на диске будет проверено перед загрузкой. EXE пока без подписи Windows: Smart App Control может запретить запуск.');note.setWordWrap(True);note.setMinimumHeight(72);box.addWidget(note)
   self.status=QLabel('Готово к установке');self.status.setWordWrap(True);box.addWidget(self.status)
   self.bar=QProgressBar();self.bar.setRange(0,100);self.bar.setValue(0);box.addWidget(self.bar)
   self.go=QPushButton('Скачать и установить');self.go.setObjectName('primaryAction');self.go.clicked.connect(self.start);box.addWidget(self.go)
   self.open=QPushButton('Открыть папку установки');self.open.setVisible(False);self.open.clicked.connect(lambda:os.startfile(str(self.target.parent)));box.addWidget(self.open)
   self.launch=QPushButton('Запустить NEXUS');self.launch.setVisible(False);self.launch.clicked.connect(self.run_launcher);box.addWidget(self.launch)
   legal=QLabel('GPL-3.0-only · Икрам Ikram / ForceCore');box.addWidget(legal)
   self.licenses=QPushButton('Лицензии компонентов');self.licenses.clicked.connect(lambda:os.startfile(str(Path(sys._MEIPASS)/'third-party-notices')));box.addWidget(self.licenses)
  def browse(self):
   value=QFileDialog.getExistingDirectory(self,'Выберите папку установки',self.path.text())
   if value:self.path.setText(str(Path(value)/'NEXUS Launcher'))
  def start(self):
   if self.worker:return
   self.go.setEnabled(False);self.choose.setEnabled(False);self.path.setEnabled(False);self.title_bar.close_button.setEnabled(False)
   self.worker=Worker(Path(self.path.text()),self);self.worker.progress.connect(self.progress);self.worker.finished_install.connect(self.result);self.worker.finished.connect(self.done_worker);self.worker.start()
  def progress(self,value):
   phase,done,total=value
   self.status.setText({'CHECKING':'Проверяем выпуск…','DOWNLOADING':'Скачиваем полный лаунчер…','VERIFYING':'Проверяем и распаковываем файлы…','COMPLETE':'Лаунчер установлен.'}[phase])
   self.bar.setRange(0,100 if total else 0)
   if total:self.bar.setValue(min(99,done*100//total))
  def result(self,result):
   target,error=result;self.target=Path(target) if target else None;self.status.setText(error or 'Установка завершена. Можно запускать NEXUS.');self.bar.setRange(0,100);self.bar.setValue(100 if target else 0)
  def done_worker(self):
   self.worker.deleteLater();self.worker=None;self.title_bar.close_button.setEnabled(True)
   self.go.setVisible(self.target is None);self.go.setEnabled(True);self.choose.setEnabled(self.target is None);self.path.setEnabled(self.target is None)
   self.open.setVisible(self.target is not None);self.launch.setVisible(self.target is not None)
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
   if self.worker is None:super().reject()
  def closeEvent(self,event):
   if self.worker:event.ignore()
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
