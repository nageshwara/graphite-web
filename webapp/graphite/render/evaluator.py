import time
import threading
from django.conf import settings
from graphite.render.grammar import grammar
from graphite.render.functions import SeriesFunctions
from graphite.render.datatypes import TimeSeries
from graphite.render.carbonlink import CarbonLink
from graphite.logger import log



def evaluateTarget(target, timeInterval):
  tokens = grammar.parseString(target)
  result = evaluateTokens(tokens, timeInterval)

  if type(result) is TimeSeries:
    return [result] #we have to return a list of TimeSeries objects

  else:
    return result


class fetchData(threading.Thread):
  def __init__ (self,timeInterval, dbFile):
    threading.Thread.__init__(self)
    self.timeInterval = timeInterval
    self.dbFile = dbFile
  def run(self):
    t = time.time()
    (startTime,endTime) = self.timeInterval
    getCacheResults = CarbonLink.sendRequest(self.dbFile.real_metric)
    dbResults = self.dbFile.fetch( timestamp(startTime), timestamp(endTime) )
    self.results = mergeResults(dbResults, getCacheResults())
#    log.info("Retrieval of %s took %.6f" % (self.dbFile.metric_path,time.time() - t))


def evaluateTokens(tokens, timeInterval):
  if tokens.expression:
    return evaluateTokens(tokens.expression, timeInterval)

  elif tokens.pathExpression:
    pathExpr = tokens.pathExpression

    if pathExpr.lower().startswith('graphite.'):
      pathExpr = pathExpr[9:]

    seriesList = []
    (startTime,endTime) = timeInterval

    threads = []
    for dbFile in settings.STORE.find(pathExpr):
      threads.append(fetchData(timeInterval, dbFile))
      threads[-1].start()

    for thread in threads:
      thread.join()
      results = thread.results
      dbFile = thread.dbFile
      if not results:
        continue

      (timeInfo,values) = results
      (start,end,step) = timeInfo
      series = TimeSeries(dbFile.metric_path, start, end, step, values)
      series.pathExpression = pathExpr #hack to pass expressions through to render functions
      seriesList.append(series)

    return seriesList

  elif tokens.call:
    func = SeriesFunctions[tokens.call.func]
    args = [evaluateTokens(arg, timeInterval) for arg in tokens.call.args]
    return func(*args)

  elif tokens.number:
    if tokens.number.integer:
      return int(tokens.number.integer)

    elif tokens.number.float:
      return float(tokens.number.float)

  elif tokens.string:
    return str(tokens.string)[1:-1]


def timestamp(datetime):
  "Convert a datetime object into epoch time"
  return time.mktime( datetime.timetuple() )


def mergeResults(dbResults, cacheResults):
  cacheResults = list(cacheResults)

  if not dbResults:
    return cacheResults
  elif not cacheResults:
    return dbResults

  (timeInfo,values) = dbResults
  (start,end,step) = timeInfo

  for (timestamp,value) in cacheResults:
    interval = timestamp - (timestamp % step)

    try:
      i = int(interval - start) / step
      values[i] = value
    except:
      pass

  return (timeInfo,values)