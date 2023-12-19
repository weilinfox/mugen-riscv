import json

class combination:
    
    def __init__(self):
        self.env = [
            {
                "type": "host",
                "name": "host_1",
                "ip": "127.0.0.1",
                "password": "openEuler12#$",
                "port": "22",
                "user": "root",
            }
        ]
        self.combinations = [ 
            {
                "name": "mugen_test",
                "testcases": [
                ]
            }
        ]
        self.execute = [
            {
                "env":["host_1"],
                "combination":"mugen_test"
            }
        ]

    def add_case(self , testsuite , testcase):
        flag = False
        for suite in self.combinations[0]['testcases']:
            if suite['testsuite'] == testsuite:
                if testcase not in suite['add']:
                    suite['add'].append(testcase)
                    flag = True
                    break
        
        if not flag:
            self.combinations[0]['testcases'].append(
                {
                    "testsuite":testsuite ,
                    "add":[testcase]
                }
            )

    def export_json(self):
        dicts = {
            'env' : self.env , 
            'combination' : self.combinations , 
            'execute' : self.execute
        }
        with open('test.json' , 'w') as f:
            f.write(json.dumps(dicts , indent=4))
    
    def export_one_json(self , testsuite , path='.' , id=0):
        dicts = {
            'env' : self.env , 
            'combination' : [
                {
                    "name": "mugen_test",
                    "testcases": [
                    ]
                }
            ],
            'execute' : self.execute 
        }
        for testcase in self.combinations[0]['testcases']:
            if testcase['testsuite'] == testsuite:
                dicts['combination'][0]['testcases'].append(testcase) 
        if not dicts['combination'][0]['testcases']:
            print('no such testsuite: ',testsuite)
            exit(-1)
        with open(path+'/'+testsuite+'_'+str(id)+'.json' , 'w') as f:
            f.write(json.dumps(dicts , indent=4))

    def export_every_json(self):
        for testsuite in self.combinations[0]['testcases']:
            dicts = {
                'env' : self.env , 
                'combination' : [
                    {
                        "name": "mugen_test",
                        "testcases": [
                            testsuite
                        ]
                    }
                ] , 
                  
            }
            with open(testsuite['testsuite']+'_test.json' , 'w') as f:
                f.write(json.dumps(dicts , indent=4))

    def clear_one_testsuite(self , testsuite):
        for testsuite1 in combination[0]['testcases']:
            if testsuite1['testsuite'] == testsuite:
                combination['testcases'].remove(testsuite1)
                break
