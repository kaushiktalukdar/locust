import gevent
from gevent import sleep
from gevent.pool import Group

from locust.exception import InterruptTaskSet, ResponseError
from locust import HttpUser, User, TaskSet, task, tag, between, constant
from locust.user.task import filter_tasks_by_tags
from locust.env import Environment
from locust.exception import (CatchResponseError, LocustError, RescheduleTask,
                              RescheduleTaskImmediately, StopUser)

from .testcases import LocustTestCase, WebserverTestCase


class TestTaskSet(LocustTestCase):
    def setUp(self):
        super(TestTaskSet, self).setUp()
        
        class MyUser(User):
            host = "127.0.0.1"
        self.locust = MyUser(self.environment)

    def test_task_ratio(self):
        t1 = lambda l: None
        t2 = lambda l: None
        class MyTasks(TaskSet):
            tasks = {t1:5, t2:2}
        
        l = MyTasks(self.locust)

        t1_count = len([t for t in l.tasks if t == t1])
        t2_count = len([t for t in l.tasks if t == t2])

        self.assertEqual(t1_count, 5)
        self.assertEqual(t2_count, 2)
    
    def test_tasks_missing_gives_user_friendly_exception(self):
        class MyTasks(TaskSet):
            tasks = None

        class MyUser(User):
            wait_time = constant(0.5)
            tasks = [MyTasks]
        
        l = MyTasks(MyUser(self.environment))
        self.assertRaisesRegex(Exception, "No tasks defined.*", l.run)
        l.tasks = []
        self.assertRaisesRegex(Exception, "No tasks defined.*", l.run)

    def test_task_decorator_ratio(self):
        t1 = lambda l: None
        t2 = lambda l: None
        class MyTasks(TaskSet):
            tasks = {t1:5, t2:2}
            host = ""
            
            @task(3)
            def t3(self):
                pass
            
            @task(13)
            def t4(self):
                pass
            

        l = MyTasks(self.locust)

        t1_count = len([t for t in l.tasks if t == t1])
        t2_count = len([t for t in l.tasks if t == t2])
        t3_count = len([t for t in l.tasks if t.__name__ == MyTasks.t3.__name__])
        t4_count = len([t for t in l.tasks if t.__name__ == MyTasks.t4.__name__])

        self.assertEqual(t1_count, 5)
        self.assertEqual(t2_count, 2)
        self.assertEqual(t3_count, 3)
        self.assertEqual(t4_count, 13)
    
    def test_tasks_on_locust(self):
        class MyUser(User):
            @task(2)
            def t1(self):
                pass
            @task(3)
            def t2(self):
                pass
        l = MyUser(self.environment)
        self.assertEqual(2, len([t for t in l.tasks if t.__name__ == MyUser.t1.__name__]))
        self.assertEqual(3, len([t for t in l.tasks if t.__name__ == MyUser.t2.__name__]))
    
    def test_tasks_on_abstract_locust(self):
        class AbstractUser(User):
            abstract = True
            @task(2)
            def t1(self):
                pass
        class MyUser(AbstractUser):
            @task(3)
            def t2(self):
                pass
        l = MyUser(self.environment)
        self.assertEqual(2, len([t for t in l.tasks if t.__name__ == MyUser.t1.__name__]))
        self.assertEqual(3, len([t for t in l.tasks if t.__name__ == MyUser.t2.__name__]))

    def test_taskset_on_abstract_locust(self):
        v = [0]
        class AbstractUser(User):
            abstract = True
            @task
            class task_set(TaskSet):
                @task
                def t1(self):
                    v[0] = 1
                    raise StopUser()
        class MyUser(AbstractUser):
            pass
        l = MyUser(self.environment)
        # check that the User can be run
        l.run()
        self.assertEqual(1, v[0])
    
    def test_task_decorator_on_taskset(self):
        state = [0]
        class MyUser(User):
            wait_time = constant(0)
            @task
            def t1(self):
                pass
            @task
            class MyTaskSet(TaskSet):
                @task
                def subtask(self):
                    state[0] = 1
                    raise StopUser()
        
        self.assertEqual([MyUser.t1, MyUser.MyTaskSet], MyUser.tasks)
        MyUser(self.environment).run()
        self.assertEqual(1, state[0])

    def test_on_start(self):
        class MyTasks(TaskSet):
            t1_executed = False
            t2_executed = False
            
            def on_start(self):
                self.t1()
            
            def t1(self):
                self.t1_executed = True
            
            @task
            def t2(self):
                self.t2_executed = True
                raise InterruptTaskSet(reschedule=False)

        l = MyTasks(self.locust)
        self.assertRaises(RescheduleTask, lambda: l.run())
        self.assertTrue(l.t1_executed)
        self.assertTrue(l.t2_executed)
    
    def test_on_stop_interrupt(self):
        class MyTasks(TaskSet):
            t2_executed = False
            on_stop_executed = False
    
            def on_stop(self):
                self.on_stop_executed = True
    
            @task
            def t2(self):
                self.t2_executed = True
                self.interrupt(reschedule=False)
        
        ts = MyTasks(self.locust)
        self.assertRaises(RescheduleTask, lambda: ts.run())
        self.assertTrue(ts.t2_executed)
        self.assertTrue(ts.on_stop_executed)
    
    def test_on_stop_interrupt_reschedule(self):
        class MyTasks(TaskSet):
            t2_executed = False
            on_stop_executed = False

            def on_stop(self):
                self.on_stop_executed = True

            @task
            def t2(self):
                self.t2_executed = True
                self.interrupt(reschedule=True)

        ts = MyTasks(self.locust)
        self.assertRaises(RescheduleTaskImmediately, lambda: ts.run())
        self.assertTrue(ts.t2_executed)
        self.assertTrue(ts.on_stop_executed)
    
    def test_on_stop_when_locust_stops(self):
        class MyTasks(TaskSet):
            def on_stop(self):
                self.user.on_stop_executed = True

            @task
            def t2(self):
                self.user.t2_executed = True
        
        class MyUser(User):
            t2_executed = False
            on_stop_executed = False
            
            tasks = [MyTasks]
            wait_time = constant(0.1)
        
        group = Group()
        user = MyUser(self.environment)
        user.start(group)
        sleep(0.05)
        user.stop(group)
        sleep(0)
        
        self.assertTrue(user.t2_executed)
        self.assertTrue(user.on_stop_executed)

    def test_schedule_task(self):
        self.t1_executed = False
        self.t2_arg = None

        def t1(l):
            self.t1_executed = True

        def t2(l, arg):
            self.t2_arg = arg

        class MyTasks(TaskSet):
            tasks = [t1, t2]

        taskset = MyTasks(self.locust)
        taskset.schedule_task(t1)
        taskset.execute_next_task()
        self.assertTrue(self.t1_executed)

        taskset.schedule_task(t2, args=["argument to t2"])
        taskset.execute_next_task()
        self.assertEqual("argument to t2", self.t2_arg)
    
    def test_schedule_task_with_kwargs(self):
        class MyTasks(TaskSet):
            @task
            def t1(self):
                self.t1_executed = True
            @task
            def t2(self, *args, **kwargs):
                self.t2_args = args
                self.t2_kwargs = kwargs
        loc = MyTasks(self.locust)
        loc.schedule_task(loc.t2, [42], {"test_kw":"hello"})
        loc.execute_next_task()
        self.assertEqual((42, ), loc.t2_args)
        self.assertEqual({"test_kw":"hello"}, loc.t2_kwargs)
        
        loc.schedule_task(loc.t2, args=[10, 4], kwargs={"arg1":1, "arg2":2})
        loc.execute_next_task()
        self.assertEqual((10, 4), loc.t2_args)
        self.assertEqual({"arg1":1, "arg2":2}, loc.t2_kwargs)
    
    def test_schedule_task_bound_method(self):
        class MyTasks(TaskSet):
            host = ""
            
            @task()
            def t1(self):
                self.t1_executed = True
                self.schedule_task(self.t2)
            def t2(self):
                self.t2_executed = True
        
        taskset = MyTasks(self.locust)
        taskset.schedule_task(taskset.get_next_task())
        taskset.execute_next_task()
        self.assertTrue(taskset.t1_executed)
        taskset.execute_next_task()
        self.assertTrue(taskset.t2_executed)
        
    
    def test_taskset_inheritance(self):
        def t1(l):
            pass
        class MyBaseTaskSet(TaskSet):
            tasks = [t1]
            host = ""
        class MySubTaskSet(MyBaseTaskSet):
            @task
            def t2(self):
                pass
        
        l = MySubTaskSet(self.locust)
        self.assertEqual(2, len(l.tasks))
        self.assertEqual([t1, MySubTaskSet.t2], l.tasks)
    
    def test_task_decorator_with_or_without_argument(self):
        class MyTaskSet(TaskSet):
            @task
            def t1(self):
                pass
        taskset = MyTaskSet(self.locust)
        self.assertEqual(len(taskset.tasks), 1)
        
        class MyTaskSet2(TaskSet):
            @task()
            def t1(self):
                pass
        taskset = MyTaskSet2(self.locust)
        self.assertEqual(len(taskset.tasks), 1)
        
        class MyTaskSet3(TaskSet):
            @task(3)
            def t1(self):
                pass
        taskset = MyTaskSet3(self.locust)
        self.assertEqual(len(taskset.tasks), 3)
    
    
    def test_wait_function(self):
        class MyTaskSet(TaskSet):
            a = 1
            b = 2
            wait_time = lambda self: 1 + (self.b-self.a)
        taskset = MyTaskSet(self.locust)
        self.assertEqual(taskset.wait_time(), 2.0)
    
    def test_sub_taskset(self):
        class MySubTaskSet(TaskSet):
            constant(1)
            @task()
            def a_task(self):
                self.user.sub_locust_task_executed = True
                self.interrupt()
            
        class MyTaskSet(TaskSet):
            tasks = [MySubTaskSet]
        
        self.sub_locust_task_executed = False
        loc = MyTaskSet(self.locust)
        loc.schedule_task(loc.get_next_task())
        self.assertRaises(RescheduleTaskImmediately, lambda: loc.execute_next_task())
        self.assertTrue(self.locust.sub_locust_task_executed)
    
    def test_sub_taskset_tasks_decorator(self):
        class MyTaskSet(TaskSet):
            @task
            class MySubTaskSet(TaskSet):
                wait_time = constant(0.001)
                @task()
                def a_task(self):
                    self.user.sub_locust_task_executed = True
                    self.interrupt()
        
        self.sub_locust_task_executed = False
        loc = MyTaskSet(self.locust)
        loc.schedule_task(loc.get_next_task())
        self.assertRaises(RescheduleTaskImmediately, lambda: loc.execute_next_task())
        self.assertTrue(self.locust.sub_locust_task_executed)
    
    def test_sub_taskset_arguments(self):
        class MySubTaskSet(TaskSet):
            wait_time = constant(0.001)
            @task()
            def a_task(self):
                self.user.sub_taskset_args = self.args
                self.user.sub_taskset_kwargs = self.kwargs
                self.interrupt()
        class MyTaskSet(TaskSet):
            sub_locust_args = None
            sub_locust_kwargs = None
            tasks = [MySubTaskSet]
        
        self.locust.sub_taskset_args = None
        self.locust.sub_taskset_kwargs = None
        
        loc = MyTaskSet(self.locust)
        loc.schedule_task(MySubTaskSet, args=[1,2,3], kwargs={"hello":"world"})
        self.assertRaises(RescheduleTaskImmediately, lambda: loc.execute_next_task())
        self.assertEqual((1,2,3), self.locust.sub_taskset_args)
        self.assertEqual({"hello":"world"}, self.locust.sub_taskset_kwargs)
    
    def test_on_start_interrupt(self):
        class SubTaskSet(TaskSet):
            def on_start(self):
                if self.kwargs["reschedule"]:
                    self.interrupt(reschedule=True)
                else:
                    self.interrupt(reschedule=False)

        class MyUser(User):
            host = ""
            tasks = [SubTaskSet]
        
        l = MyUser(Environment())
        task_set = SubTaskSet(l)
        self.assertRaises(RescheduleTaskImmediately, lambda: task_set.run(reschedule=True))
        self.assertRaises(RescheduleTask, lambda: task_set.run(reschedule=False))

    
    def test_parent_attribute(self):
        from locust.exception import StopUser
        parents = {}
        
        class SubTaskSet(TaskSet):
            def on_start(self):
                parents["sub"] = self.parent
            
            @task
            class SubSubTaskSet(TaskSet):
                def on_start(self):
                    parents["subsub"] = self.parent
                @task
                def stop(self):
                    raise StopUser()
        class RootTaskSet(TaskSet):
            tasks = [SubTaskSet]
        
        class MyUser(User):
            host = ""
            tasks = [RootTaskSet]
        
        l = MyUser(Environment())
        l.run()
        self.assertTrue(isinstance(parents["sub"], RootTaskSet))
        self.assertTrue(isinstance(parents["subsub"], SubTaskSet))

    def test_tagging(self):
        @tag('tag1')
        @task
        def tagged():
            pass

        self.assertIn('locust_tag_set', dir(tagged))
        self.assertEqual(set(['tag1']), tagged.locust_tag_set)

        @tag('tag2', 'tag3')
        @task
        def tagged_multiple_args():
            pass

        self.assertIn('locust_tag_set', dir(tagged_multiple_args))
        self.assertEqual(set(['tag2', 'tag3']), tagged_multiple_args.locust_tag_set)

        @tag('tag4')
        @tag('tag5')
        @task
        def tagged_multiple_times():
            pass
        self.assertIn('locust_tag_set', dir(tagged_multiple_times))
        self.assertEqual(set(['tag4', 'tag5']), tagged_multiple_times.locust_tag_set)

    def test_tagging_taskset(self):
        @tag('taskset')
        @task
        class MyTaskSet(TaskSet):
            @task
            def tagged(self):
                pass

            @tag('task')
            @task
            def tagged_again(self):
                pass

            @tag('taskset2')
            @task
            class NestedTaskSet(TaskSet):
                @task
                def nested_task(self):
                    pass

        # when tagging taskset, its tasks recieve the tag
        self.assertIn('locust_tag_set', dir(MyTaskSet.tagged))
        self.assertEqual(set(['taskset']), MyTaskSet.tagged.locust_tag_set)

        # tagging inner task receives both
        self.assertIn('locust_tag_set', dir(MyTaskSet.tagged_again))
        self.assertEqual(set(['taskset', 'task']), MyTaskSet.tagged_again.locust_tag_set)

        # when tagging nested taskset, its tasks receives both
        self.assertIn('locust_tag_set', dir(MyTaskSet.NestedTaskSet.nested_task))
        self.assertEqual(set(['taskset', 'taskset2']), MyTaskSet.NestedTaskSet.nested_task.locust_tag_set)

    def test_tagging_without_args_fails(self):
        @task
        def dummy_task(self):
            pass

        # task is tagged without parens
        self.assertRaises(ValueError, lambda: tag(dummy_task))

        # task is tagged with empty parens
        self.assertRaises(ValueError, lambda: tag()(dummy_task))

    def test_including_tags(self):
        class MyTaskSet(TaskSet):
            @tag('include this', 'other tag')
            @task(2)
            def included(self):
                pass

            @tag('dont include this', 'other tag')
            @task
            def not_included(self):
                pass

            @task
            def dont_include_this_either(self):
                pass

        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.included, MyTaskSet.included, MyTaskSet.not_included, MyTaskSet.dont_include_this_either])

        filter_tasks_by_tags(MyTaskSet, tags=set(['include this']))
        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.included, MyTaskSet.included])

    def test_excluding_tags(self):
        class MyTaskSet(TaskSet):
            @tag('exclude this', 'other tag')
            @task(2)
            def excluded(self):
                pass

            @tag('dont exclude this', 'other tag')
            @task
            def not_excluded(self):
                pass

            @task
            def dont_exclude_this_either(self):
                pass

        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.excluded, MyTaskSet.excluded, MyTaskSet.not_excluded, MyTaskSet.dont_exclude_this_either])

        filter_tasks_by_tags(MyTaskSet, exclude_tags=set(['exclude this']))
        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.not_excluded, MyTaskSet.dont_exclude_this_either])

    def test_including_and_excluding(self):
        class MyTaskSet(TaskSet):
            @task
            def not_included_or_excluded(self):
                pass

            @tag('included')
            @task
            def included(self):
                pass

            @tag('excluded')
            @task
            def excluded(self):
                pass

            @tag('included', 'excluded')
            @task
            def included_and_excluded(self):
                pass

        filter_tasks_by_tags(MyTaskSet, tags=set(['included']), exclude_tags=set(['excluded']))
        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.included])

    def test_including_tasksets(self):
        class MyTaskSet(TaskSet):
            @task
            class MixedNestedTaskSet(TaskSet):
                @tag('included')
                @task
                def included(self):
                    pass

                @task
                def not_included(self):
                    pass

            @tag('included')
            @task
            class TaggedNestedTaskSet(TaskSet):
                @task
                def included(self):
                    pass

            @task
            class NormalNestedTaskSet(TaskSet):
                @task
                def not_included(self):
                    pass

        filter_tasks_by_tags(MyTaskSet, tags=set(['included']))
        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.MixedNestedTaskSet, MyTaskSet.TaggedNestedTaskSet])
        self.assertListEqual(MyTaskSet.MixedNestedTaskSet.tasks, [MyTaskSet.MixedNestedTaskSet.included])

    def test_excluding_tasksets(self):
        class MyTaskSet(TaskSet):
            @task
            class MixedNestedTaskSet(TaskSet):
                @tag('excluded')
                @task
                def excluded(self):
                    pass

                @task
                def not_excluded(self):
                    pass

            @task
            class ExcludedNestedTaskSet(TaskSet):
                @tag('excluded')
                @task
                def excluded(self):
                    pass

            @tag('excluded')
            @task
            class TaggedNestedTaskSet(TaskSet):
                @task
                def excluded(self):
                    pass

            @task
            class NormalNestedTaskSet(TaskSet):
                @task
                def not_excluded(self):
                    pass

        filter_tasks_by_tags(MyTaskSet, exclude_tags=set(['excluded']))
        self.assertListEqual(MyTaskSet.tasks, [MyTaskSet.MixedNestedTaskSet, MyTaskSet.NormalNestedTaskSet])
        self.assertListEqual(MyTaskSet.MixedNestedTaskSet.tasks, [MyTaskSet.MixedNestedTaskSet.not_excluded])


class TestLocustClass(LocustTestCase):
    def test_locust_wait(self):
        log = []
        class TestUser(User):
            wait_time = constant(0.01)
            @task
            def t(self):
                log.append(0)
                self.wait()
                log.append(1)
                raise StopUser()

        l = TestUser(self.environment)
        l.run()
        self.assertEqual([0,1], log)

    def test_locust_on_start(self):
        class MyUser(User):
            t1_executed = False
            t2_executed = False
    
            def on_start(self):
                self.t1()
    
            def t1(self):
                self.t1_executed = True
    
            @task
            def t2(self):
                self.t2_executed = True
                raise StopUser()
    
        l = MyUser(self.environment)
        l.run()
        self.assertTrue(l.t1_executed)
        self.assertTrue(l.t2_executed)
    
    def test_locust_on_stop(self):
        class MyUser(User):
            on_stop_executed = False
            t2_executed = True

            def on_stop(self):
                self.on_stop_executed = True

            @task
            def t2(self):
                self.t2_executed = True
                raise StopUser()

        l = MyUser(self.environment)
        l.run()
        self.assertTrue(l.on_stop_executed)
        self.assertTrue(l.t2_executed)
    
    def test_locust_start(self):
        class TestUser(User):
            wait_time = constant(0.1)
            test_state = 0
            @task
            def t(self):
                self.test_state = 1
                sleep(0.1)
                raise StopUser()
        group = Group()
        user = TestUser(self.environment)
        greenlet = user.start(group)
        sleep(0)
        self.assertEqual(1, len(group))
        self.assertIn(greenlet, group)
        self.assertEqual(1, user.test_state)
        timeout = gevent.Timeout(1)
        timeout.start()
        group.join()
        timeout.cancel()
    
    def test_locust_graceful_stop(self):
        class TestUser(User):
            wait_time = constant(0)
            test_state = 0
            @task
            def t(self):
                self.test_state = 1
                sleep(0.1)
                self.test_state = 2
        
        group = Group()
        user = TestUser(self.environment)
        greenlet = user.start(group)
        sleep(0)
        self.assertEqual(1, user.test_state)
        
        # stop User gracefully
        user.stop(group, force=False)
        sleep(0)
        # make sure instance is not killed right away
        self.assertIn(greenlet, group)
        self.assertEqual(1, user.test_state)
        sleep(0.2)
        # check that locust instance has now died and that the task got to finish
        self.assertEqual(0, len(group))
        self.assertEqual(2, user.test_state)
    
    def test_locust_forced_stop(self):
        class TestUser(User):
            wait_time = constant(0)
            test_state = 0
            @task
            def t(self):
                self.test_state = 1
                sleep(0.1)
                self.test_state = 2
    
        group = Group()
        user = TestUser(self.environment)
        greenlet = user.start(group)
        sleep(0)
        self.assertIn(greenlet, group)
        self.assertEqual(1, user.test_state)
    
        # stop User gracefully
        user.stop(group, force=True)
        sleep(0)
        # make sure instance is killed right away, and that the task did NOT get to finish
        self.assertEqual(0, len(group))
        self.assertEqual(1, user.test_state)


class TestWebLocustClass(WebserverTestCase):
    def test_get_request(self):
        self.response = ""
        def t1(l):
            self.response = l.client.get("/ultra_fast")
        class MyUser(HttpUser):
            tasks = [t1]
            host = "http://127.0.0.1:%i" % self.port

        my_locust = MyUser(self.environment)
        t1(my_locust)
        self.assertEqual(self.response.text, "This is an ultra fast response")

    def test_client_request_headers(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual("hello", locust.client.get("/request_header_test", headers={"X-Header-Test":"hello"}).text)

    def test_client_get(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual("GET", locust.client.get("/request_method").text)
    
    def test_client_get_absolute_url(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual("GET", locust.client.get("http://127.0.0.1:%i/request_method" % self.port).text)

    def test_client_post(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual("POST", locust.client.post("/request_method", {"arg":"hello world"}).text)
        self.assertEqual("hello world", locust.client.post("/post", {"arg":"hello world"}).text)

    def test_client_put(self):
        class MyUserHttpUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUserHttpUser(self.environment)
        self.assertEqual("PUT", locust.client.put("/request_method", {"arg":"hello world"}).text)
        self.assertEqual("hello world", locust.client.put("/put", {"arg":"hello world"}).text)

    def test_client_delete(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual("DELETE", locust.client.delete("/request_method").text)
        self.assertEqual(200, locust.client.delete("/request_method").status_code)

    def test_client_head(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        self.assertEqual(200, locust.client.head("/request_method").status_code)

    def test_client_basic_auth(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        class MyAuthorizedUser(HttpUser):
            host = "http://locust:menace@127.0.0.1:%i" % self.port

        class MyUnauthorizedUser(HttpUser):
            host = "http://locust:wrong@127.0.0.1:%i" % self.port

        locust = MyUser(self.environment)
        unauthorized = MyUnauthorizedUser(self.environment)
        authorized = MyAuthorizedUser(self.environment)
        response = authorized.client.get("/basic_auth")
        self.assertEqual(200, response.status_code)
        self.assertEqual("Authorized", response.text)
        self.assertEqual(401, locust.client.get("/basic_auth").status_code)
        self.assertEqual(401, unauthorized.client.get("/basic_auth").status_code)
    
    def test_log_request_name_argument(self):
        class MyUser(HttpUser):
            tasks = []
            host = "http://127.0.0.1:%i" % self.port
            
            @task()
            def t1(l):
                l.client.get("/ultra_fast", name="new name!")

        my_locust = MyUser(self.environment)
        my_locust.t1()
        
        self.assertEqual(1, self.runner.stats.get("new name!", "GET").num_requests)
        self.assertEqual(0, self.runner.stats.get("/ultra_fast", "GET").num_requests)
    
    def test_locust_client_error(self):
        class MyTaskSet(TaskSet):
            @task
            def t1(self):
                self.client.get("/")
                self.interrupt()
        
        class MyUser(User):
            host = "http://127.0.0.1:%i" % self.port
            tasks = [MyTaskSet]
        
        my_locust = MyUser(self.environment)
        self.assertRaises(LocustError, lambda: my_locust.client.get("/"))
        my_taskset = MyTaskSet(my_locust)
        self.assertRaises(LocustError, lambda: my_taskset.client.get("/"))
    
    def test_redirect_url_original_path_as_name(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        l = MyUser(self.environment)
        l.client.get("/redirect")
        
        self.assertEqual(1, len(self.runner.stats.entries))
        self.assertEqual(1, self.runner.stats.get("/redirect", "GET").num_requests)
        self.assertEqual(0, self.runner.stats.get("/ultra_fast", "GET").num_requests)


class TestCatchResponse(WebserverTestCase):
    def setUp(self):
        super(TestCatchResponse, self).setUp()
        
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port

        self.locust = MyUser(self.environment)
        
        self.num_failures = 0
        self.num_success = 0
        def on_failure(request_type, name, response_time, response_length, exception):
            self.num_failures += 1
            self.last_failure_exception = exception
        def on_success(**kwargs):
            self.num_success += 1
        self.environment.events.request_failure.add_listener(on_failure)
        self.environment.events.request_success.add_listener(on_success)
        
    def test_catch_response(self):
        self.assertEqual(500, self.locust.client.get("/fail").status_code)
        self.assertEqual(1, self.num_failures)
        self.assertEqual(0, self.num_success)
        
        with self.locust.client.get("/ultra_fast", catch_response=True) as response: pass
        self.assertEqual(1, self.num_failures)
        self.assertEqual(1, self.num_success)
        
        with self.locust.client.get("/ultra_fast", catch_response=True) as response:
            raise ResponseError("Not working")
        
        self.assertEqual(2, self.num_failures)
        self.assertEqual(1, self.num_success)
    
    def test_catch_response_http_fail(self):
        with self.locust.client.get("/fail", catch_response=True) as response: pass
        self.assertEqual(1, self.num_failures)
        self.assertEqual(0, self.num_success)
    
    def test_catch_response_http_manual_fail(self):
        with self.locust.client.get("/ultra_fast", catch_response=True) as response:
            response.failure("Haha!")
        self.assertEqual(1, self.num_failures)
        self.assertEqual(0, self.num_success)
        self.assertTrue(
            isinstance(self.last_failure_exception, CatchResponseError),
            "Failure event handler should have been passed a CatchResponseError instance"
        )
    
    def test_catch_response_http_manual_success(self):
        with self.locust.client.get("/fail", catch_response=True) as response:
            response.success()
        self.assertEqual(0, self.num_failures)
        self.assertEqual(1, self.num_success)
    
    def test_catch_response_allow_404(self):
        with self.locust.client.get("/does/not/exist", catch_response=True) as response:
            self.assertEqual(404, response.status_code)
            if response.status_code == 404:
                response.success()
        self.assertEqual(0, self.num_failures)
        self.assertEqual(1, self.num_success)
    
    def test_interrupt_taskset_with_catch_response(self):
        class MyTaskSet(TaskSet):
            @task
            def interrupted_task(self):
                with self.client.get("/ultra_fast", catch_response=True) as r:
                    raise InterruptTaskSet()
        class MyUser(HttpUser):
            host = "http://127.0.0.1:%i" % self.port
            tasks = [MyTaskSet]
        
        l = MyUser(self.environment)
        ts = MyTaskSet(l)
        self.assertRaises(InterruptTaskSet, lambda: ts.interrupted_task())
        self.assertEqual(0, self.num_failures)
        self.assertEqual(0, self.num_success)
    
    def test_catch_response_connection_error_success(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:1"
        l = MyUser(self.environment)
        with l.client.get("/", catch_response=True) as r:
            self.assertEqual(r.status_code, 0)
            self.assertEqual(None, r.content)
            r.success()
        self.assertEqual(1, self.num_success)
        self.assertEqual(0, self.num_failures)
    
    def test_catch_response_connection_error_fail(self):
        class MyUser(HttpUser):
            host = "http://127.0.0.1:1"
        l = MyUser(self.environment)
        with l.client.get("/", catch_response=True) as r:
            self.assertEqual(r.status_code, 0)
            self.assertEqual(None, r.content)
            r.failure("Manual fail")
        self.assertEqual(0, self.num_success)
        self.assertEqual(1, self.num_failures)
