# vim : fileencoding=UTF-8 :

from __future__ import absolute_import, division, unicode_literals

import logging
import multiprocessing
import threading
# Bu kod, bir çoklu işlem desteği sunan bir Python kayıt modülü olarak kullanılabilecek
# bir sınıf olan MultiProcessingHandler sınıfını ve bu sınıfın iki yardımcı fonksiyonunu içerir.
# MultiProcessingHandler sınıfı, çoklu işlem desteği sunan bir işleyici olarak davranır ve
# bir kayıtçının yerine kullanılabilir.
#


try:
    from queue import Empty
except ImportError:  # Python 2.
    from Queue import Empty  # type: ignore[no-redef]


__version__ = "0.3.4"


def install_mp_handler(logger=None):
    """Wraps the handlers in the given Logger with an MultiProcessingHandler.
    :param logger: whose handlers to wrap. By default, the root logger.
    """
    # install_mp_handler() fonksiyonu, belirtilen Logger nesnesinin işleyicilerini MultiProcessingHandler nesnesiyle değiştirir. Varsayılan olarak, root logger'ın işleyicileri kullanılır.
    if logger is None:
        logger = logging.getLogger()

    for i, orig_handler in enumerate(list(logger.handlers)):
        handler = MultiProcessingHandler("mp-handler-{0}".format(i), sub_handler=orig_handler)

        logger.removeHandler(orig_handler)
        logger.addHandler(handler)


def uninstall_mp_handler(logger=None):
    """Unwraps the handlers in the given Logger from a MultiProcessingHandler wrapper
    :param logger: whose handlers to unwrap. By default, the root logger.
    """
    # uninstall_mp_handler() fonksiyonu, belirtilen Logger nesnesinin işleyicilerini 
    # MultiProcessingHandler nesnesinden geri alır. Varsayılan olarak, root logger'ın işleyicileri kullanılır.

    if logger is None:
        logger = logging.getLogger()

    for handler in list(logger.handlers):
        if isinstance(handler, MultiProcessingHandler):
            orig_handler = handler.sub_handler
            logger.removeHandler(handler)
            logger.addHandler(orig_handler)


class MultiProcessingHandler(logging.Handler):
    # MultiProcessingHandler sınıfı, logging.Handler sınıfını alt sınıf olarak kullanır. 
    # Bu nedenle, MultiProcessingHandler, log kayıtlarını almak ve işlemek için gerekli 
    # olan tüm yöntemlere sahiptir. Bu sınıf, bir alt işleyici olarak başka bir işleyiciyi 
    # kabul eder ve bu alt işleyiciyi kullanarak kayıtları işler. Sınıf ayrıca, bir Queue 
    # nesnesi üzerinden ana süreç ile alt işlem arasındaki iletişimi yönetir. 
    # Bu sınıfın _send() ve _receive() yöntemleri, log kayıtlarını işleyicinin alt işleyicisine 
    # gönderir ve oradan alır.
    # Bu kodda kullanılan MultiProcessingHandler sınıfı, log kayıtlarının çocuk işlemlerden 
    # ana sürece aktarılmasını sağlar. Bu, çocuk işlemlerin, ana işlemin log kayıtlarını 
    # dinleyememesi durumunda kullanışlı olabilir. Bu durum genellikle, çocuk işlemlerin 
    # fork edildiği zamanlarda meydana gelir. Çocuk işlem, ana işlemin log kayıtlarını 
    # dinleyemez çünkü birçok işletim sistemi, çocuk işlemdeki değişikliklerin ana 
    # süreçte yansıtılmamasını sağlar. Bu nedenle, MultiProcessingHandler sınıfı, 
    # bir Queue nesnesi kullanarak, log kayıtlarının çocuk işlemlerden ana sürece iletilmesini sağlar.

    def __init__(self, name, sub_handler=None):
        super(MultiProcessingHandler, self).__init__()

        if sub_handler is None:
            sub_handler = logging.StreamHandler()
        self.sub_handler = sub_handler

        self.setLevel(self.sub_handler.level)
        self.setFormatter(self.sub_handler.formatter)
        self.filters = self.sub_handler.filters

        self.queue = multiprocessing.Queue(-1)
        self._is_closed = False
        # The thread handles receiving records asynchronously.
        self._receive_thread = threading.Thread(target=self._receive, name=name)
        self._receive_thread.daemon = True
        self._receive_thread.start()

    def setFormatter(self, fmt):
        super(MultiProcessingHandler, self).setFormatter(fmt)
        self.sub_handler.setFormatter(fmt)

    def _receive(self):
        while True:
            try:
                if self._is_closed and self.queue.empty():
                    break

                record = self.queue.get(timeout=0.2)
                self.sub_handler.emit(record)
            except (KeyboardInterrupt, SystemExit):
                raise
            except (EOFError, OSError):
                break  # The queue was closed by child?
            except Empty:
                pass  # This periodically checks if the logger is closed.
            except:
                from sys import stderr
                from traceback import print_exc

                print_exc(file=stderr)
                raise

        self.queue.close()
        self.queue.join_thread()

    def _send(self, s):
        self.queue.put_nowait(s)

    def _format_record(self, record):
        # ensure that exc_info and args
        # have been stringified. Removes any chance of
        # unpickleable things inside and possibly reduces
        # message size sent over the pipe.
        if record.args:
            record.msg = record.msg % record.args
            record.args = None
        if record.exc_info:
            self.format(record)
            record.exc_info = None

        return record

    def emit(self, record):
        try:
            s = self._format_record(record)
            self._send(s)
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)

    def close(self):
        if not self._is_closed:
            self._is_closed = True
            self._receive_thread.join(5.0)  # Waits for receive queue to empty.

            self.sub_handler.close()
            super(MultiProcessingHandler, self).close()
